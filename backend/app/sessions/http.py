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
    TextSessionReadExpired,
)


router = APIRouter(prefix="/api/v1/agents/{configuration}/sessions", tags=["agents"])
InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)
IssueT = TypeVar("IssueT")


class InputIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    location: tuple[str | int, ...]
    message: str


ErrorKind = Literal[
    "unknown_configuration", "agent_unavailable", "unknown", "expired",
    "invalid_message", "busy", "not_ready", "conflict", "limit_reached", "generation_failed",
]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: ErrorKind
    turn_id: str | None = None


class InvalidInputResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["invalid_input"]
    issues: list[InputIssue]


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


class SessionCreationResponse(BaseModel):
    session_id: str
    expires_at: datetime

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
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


class CompletedTurnResponse(BaseModel):
    kind: Literal["completed"]
    turn_id: str
    message: AssistantMessageResponse
    artifacts: list[ArtifactResponse]


class ConversationTransport(Protocol):
    def create(self, value: object) -> SessionCreationResponse | JSONResponse: ...
    def read(self, session_id: str) -> SessionSnapshotResponse | JSONResponse: ...
    def append(self, session_id: str, text: str) -> UserMessageResponse | JSONResponse: ...
    async def turn(self, session_id: str) -> CompletedTurnResponse | JSONResponse: ...


@dataclass(frozen=True)
class AgentTransport(Generic[InputT, ContextT, PayloadT, IssueT]):
    agent: ConfiguredAgentService[InputT, ContextT, PayloadT, IssueT]
    input_from_json: Callable[[object], InputT]
    issue_from_domain: Callable[[IssueT], InputIssue]

    def create(self, value: object) -> SessionCreationResponse | JSONResponse:
        outcome = self.agent.create(self.input_from_json(value))
        if isinstance(outcome, AgentInputRejected):
            return _input_error(tuple(map(self.issue_from_domain, outcome.issues)))
        return SessionCreationResponse(session_id=outcome.session_id, expires_at=outcome.expires_at)

    def read(self, session_id: str) -> SessionSnapshotResponse | JSONResponse:
        outcome = self.agent.read(session_id)
        if isinstance(outcome, ConversationReadActive):
            snapshot = outcome.snapshot
            return SessionSnapshotResponse(
                session_id=snapshot.session.session_id,
                expires_at=snapshot.session.expires_at,
                messages=[_message(message) for message in snapshot.session.messages],
                artifacts=[_artifact(artifact) for artifact in snapshot.artifacts],
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

    async def turn(self, session_id: str) -> CompletedTurnResponse | JSONResponse:
        outcome = await self.agent.execute_turn(session_id)
        if outcome.kind == "completed":
            assert outcome.text is not None
            return CompletedTurnResponse(
                kind="completed", turn_id=outcome.turn_id,
                message=AssistantMessageResponse(role="assistant", text=outcome.text, turn_id=outcome.turn_id),
                artifacts=[_artifact(artifact) for artifact in outcome.artifacts],
            )
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


@router.post("", status_code=201, response_model=SessionCreationResponse, responses={
    404: {"model": ErrorResponse},
    422: {"model": InvalidInputResponse},
    503: {"model": ErrorResponse},
})
async def create_session(
    configuration: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionCreationResponse | JSONResponse:
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


@router.get("/{session_id}", response_model=SessionSnapshotResponse, responses={
    404: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
})
def read_session(
    configuration: str, session_id: str,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionSnapshotResponse | JSONResponse:
    agent = _agent(configuration, registry)
    return agent if isinstance(agent, JSONResponse) else agent.read(session_id)


@router.post("/{session_id}/messages", status_code=201, response_model=UserMessageResponse, responses={
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
})
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


@router.post("/{session_id}/turns", status_code=201, response_model=CompletedTurnResponse, responses={
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": InvalidInputResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
})
async def execute_turn(
    configuration: str, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> CompletedTurnResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    raw_body = await request.body()
    if raw_body:
        body = await _body(request)
        if body != {}:
            return _input_error((InputIssue(location=(), message="turn request must be empty"),))
    return await agent.turn(session_id)


def _user_message(value: TextMessage) -> UserMessageResponse:
    return UserMessageResponse.model_validate({"role": value.role, "text": value.text, "turn_id": value.turn_id})


def _message(value: TextMessage) -> UserMessageResponse | AssistantMessageResponse:
    if value.role == "user":
        return _user_message(value)
    return AssistantMessageResponse.model_validate({"role": value.role, "text": value.text, "turn_id": value.turn_id})


def _artifact(value: StagedArtifact[PayloadT]) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=value.artifact_id, type=value.type,
        created_at=value.created_at, order=value.order,
        turn_id=value.turn_id, payload=value.payload.model_dump(mode="json"),
    )


def _input_error(issues: tuple[InputIssue, ...]) -> JSONResponse:
    return _json(422, InvalidInputResponse(kind="invalid_input", issues=list(issues)))


def _error(kind: ErrorKind, turn_id: str | None = None) -> JSONResponse:
    statuses: dict[ErrorKind, int] = {
        "unknown_configuration": 404, "agent_unavailable": 503,
        "unknown": 404, "expired": 410, "invalid_message": 422,
        "busy": 409, "not_ready": 409, "conflict": 409,
        "limit_reached": 409, "generation_failed": 502,
    }
    return _json(statuses[kind], ErrorResponse(kind=kind, turn_id=turn_id or None))


def _json(status: int, content: ErrorResponse | InvalidInputResponse) -> JSONResponse:
    return JSONResponse(status_code=status, content=content.model_dump(mode="json", exclude_none=True))
