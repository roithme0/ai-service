"""HTTP boundary for configured conversation agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Generic, Literal, Protocol, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer

from app.agents.recipe import RecipeSessionInput
from app.agents.wiring import get_configured_agents
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.agent_service import AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationMessageBusy, ConversationReadActive, StagedArtifact, TurnKind
from app.sessions.text_sessions import (
    TextMessage, TextSessionAppendAccepted, TextSessionAppendExpired,
    TextSessionAppendInvalidMessage, TextSessionAppendLimitReached,
    TextSessionCreation, TextSessionReadExpired,
)


router = APIRouter(prefix="/api/v1/agents/{configuration}/sessions", tags=["agents"])
InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)
IssueT = TypeVar("IssueT")


class InputIssue(BaseModel):
    location: tuple[str | int, ...]
    message: str


class UserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class UserMessageResponse(BaseModel):
    role: Literal["user"]
    text: str
    turn_id: None


class AssistantMessageResponse(BaseModel):
    role: Literal["assistant"]
    text: str
    turn_id: str


MessageResponse = Annotated[UserMessageResponse | AssistantMessageResponse, Field(discriminator="role")]


class ArtifactResponse(BaseModel):
    artifact_id: str
    type: str
    created_at: datetime
    order: int
    turn_id: str
    payload: dict[str, object]

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat()


class SessionSnapshotResponse(BaseModel):
    session_id: str
    expires_at: datetime
    messages: list[MessageResponse]
    artifacts: list[ArtifactResponse]
    terminal_turn_id: str | None
    terminal_turn_kind: TurnKind | None

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return value.isoformat()


class ConversationTransport(Protocol):
    def create(self, value: object) -> JSONResponse: ...
    def read(self, session_id: str) -> SessionSnapshotResponse | JSONResponse: ...
    def append(self, session_id: str, text: str) -> UserMessageResponse | JSONResponse: ...
    async def turn(self, session_id: str) -> JSONResponse: ...


@dataclass(frozen=True)
class AgentTransport(Generic[InputT, ContextT, PayloadT, IssueT]):
    agent: ConfiguredAgentService[InputT, ContextT, PayloadT, IssueT]
    input_from_json: Callable[[object], InputT]
    issue_from_domain: Callable[[IssueT], InputIssue]

    def create(self, value: object) -> JSONResponse:
        outcome = self.agent.create(self.input_from_json(value))
        if isinstance(outcome, AgentInputRejected):
            return _json(422, {"kind": "invalid_input", "issues": [
                issue.model_dump(mode="json") for issue in map(self.issue_from_domain, outcome.issues)
            ]})
        return _json(201, _creation(outcome))

    def read(self, session_id: str) -> SessionSnapshotResponse | JSONResponse:
        outcome = self.agent.read(session_id)
        if isinstance(outcome, ConversationReadActive):
            snapshot = outcome.snapshot
            return SessionSnapshotResponse(
                session_id=snapshot.session.session_id,
                expires_at=snapshot.session.expires_at,
                messages=[_message(message) for message in snapshot.session.messages],
                artifacts=[ArtifactResponse.model_validate(_artifact(artifact)) for artifact in snapshot.artifacts],
                terminal_turn_id=snapshot.terminal_turn_id,
                terminal_turn_kind=snapshot.terminal_turn_kind,
            )
        return _error("expired" if isinstance(outcome, TextSessionReadExpired) else "unknown")

    def append(self, session_id: str, text: str) -> UserMessageResponse | JSONResponse:
        outcome = self.agent.append_user_message(session_id, text)
        if isinstance(outcome, TextSessionAppendAccepted):
            return _user_message(outcome.message)
        if isinstance(outcome, TextSessionAppendExpired):
            return _error("expired")
        if isinstance(outcome, TextSessionAppendLimitReached):
            return _error("limit_reached")
        if isinstance(outcome, TextSessionAppendInvalidMessage):
            return _error("invalid_message")
        if isinstance(outcome, ConversationMessageBusy):
            return _error("busy")
        return _error("unknown")

    async def turn(self, session_id: str) -> JSONResponse:
        outcome = await self.agent.execute_turn(session_id)
        if outcome.kind == "completed":
            assert outcome.text is not None
            return _json(201, {
                "kind": "completed", "turn_id": outcome.turn_id,
                "message": {"role": "assistant", "text": outcome.text, "turn_id": outcome.turn_id},
                "artifacts": [_artifact(artifact) for artifact in outcome.artifacts],
            })
        return _error(outcome.kind, outcome.turn_id)


def _recipe_input(value: object) -> RecipeSessionInput:
    if isinstance(value, dict):
        return RecipeSessionInput(value.get("source"), value.get("foodstuffs"))
    return RecipeSessionInput(None, None)


def _recipe_issue(issue: ValidationIssue) -> InputIssue:
    return InputIssue(location=("input", *issue.location), message=issue.message)


def _demo_issue(issue: str) -> InputIssue:
    return InputIssue(location=("input",), message=issue)


def get_agent_registry() -> dict[str, ConversationTransport | None]:
    agents = get_configured_agents()
    recipe: ConversationTransport | None = (
        AgentTransport(agents.recipe, _recipe_input, _recipe_issue) if agents.recipe else None
    )
    demo: ConversationTransport = AgentTransport(agents.demo, lambda value: value, _demo_issue)
    return {"kochwiki": recipe, "demo": demo}


def _agent(configuration: str, registry: dict[str, ConversationTransport | None]) -> ConversationTransport | JSONResponse:
    if configuration not in registry:
        return _error("unknown_configuration")
    return registry[configuration] or _error("agent_unavailable")


async def _body(request: Request) -> object:
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        return None


@router.post("", status_code=201)
async def create_session(
    configuration: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    body = await _body(request)
    if not isinstance(body, dict):
        return _input_error((InputIssue(location=(), message="request must be an object"),))
    extras = body.keys() - {"input"}
    if extras:
        return _input_error(tuple(InputIssue(location=(key,), message="extra field not permitted") for key in sorted(extras)))
    return agent.create(body.get("input"))


@router.get("/{session_id}", response_model=SessionSnapshotResponse)
def read_session(
    configuration: str, session_id: str,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionSnapshotResponse | JSONResponse:
    agent = _agent(configuration, registry)
    return agent if isinstance(agent, JSONResponse) else agent.read(session_id)


@router.post("/{session_id}/messages", status_code=201, response_model=UserMessageResponse)
async def append_message(
    configuration: str, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> UserMessageResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    try:
        message = UserMessageRequest.model_validate(await _body(request))
    except ValidationError:
        return _error("invalid_message")
    return agent.append(session_id, message.text)


@router.post("/{session_id}/turns", status_code=201)
async def execute_turn(
    configuration: str, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    raw_body = await request.body()
    if raw_body:
        body = await _body(request)
        if body != {}:
            return _input_error((InputIssue(location=(), message="turn request must be empty"),))
    return await agent.turn(session_id)


def _creation(value: TextSessionCreation) -> dict[str, str]:
    return {"session_id": value.session_id, "expires_at": value.expires_at.isoformat()}


def _user_message(value: TextMessage) -> UserMessageResponse:
    return UserMessageResponse.model_validate({"role": value.role, "text": value.text, "turn_id": value.turn_id})


def _message(value: TextMessage) -> UserMessageResponse | AssistantMessageResponse:
    if value.role == "user":
        return _user_message(value)
    return AssistantMessageResponse.model_validate({"role": value.role, "text": value.text, "turn_id": value.turn_id})


def _artifact(value: StagedArtifact[PayloadT]) -> dict[str, object]:
    return {
        "artifact_id": value.artifact_id, "type": value.type,
        "created_at": value.created_at.isoformat(), "order": value.order,
        "turn_id": value.turn_id, "payload": value.payload.model_dump(mode="json"),
    }


def _input_error(issues: tuple[InputIssue, ...]) -> JSONResponse:
    return _json(422, {"kind": "invalid_input", "issues": [issue.model_dump(mode="json") for issue in issues]})


def _error(kind: str, turn_id: str | None = None) -> JSONResponse:
    status = {
        "unknown_configuration": 404, "agent_unavailable": 503,
        "unknown": 404, "expired": 410, "invalid_message": 422,
        "busy": 409, "not_ready": 409, "conflict": 409,
        "limit_reached": 409, "generation_failed": 502,
    }[kind]
    content: dict[str, object] = {"kind": kind}
    if turn_id:
        content["turn_id"] = turn_id
    return _json(status, content)


def _json(status: int, content: object) -> JSONResponse:
    return JSONResponse(status_code=status, content=content)
