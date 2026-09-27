"""HTTP boundary for configured conversation agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents.recipe import RecipeSessionInput
from app.agents.wiring import get_configured_agents
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.agent_service import AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationMessageBusy, ConversationReadActive, StagedArtifact
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


class ConversationTransport(Protocol):
    def create(self, value: object) -> JSONResponse: ...
    def read(self, session_id: str) -> JSONResponse: ...
    def append(self, session_id: str, text: str) -> JSONResponse: ...
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

    def read(self, session_id: str) -> JSONResponse:
        outcome = self.agent.read(session_id)
        if isinstance(outcome, ConversationReadActive):
            snapshot = outcome.snapshot
            return _json(200, {
                "session_id": snapshot.session.session_id,
                "expires_at": snapshot.session.expires_at.isoformat(),
                "messages": [_message(message) for message in snapshot.session.messages],
                "artifacts": [_artifact(artifact) for artifact in snapshot.artifacts],
                "terminal_turn_id": snapshot.terminal_turn_id,
                "terminal_turn_kind": snapshot.terminal_turn_kind,
            })
        return _error("expired" if isinstance(outcome, TextSessionReadExpired) else "unknown")

    def append(self, session_id: str, text: str) -> JSONResponse:
        outcome = self.agent.append_user_message(session_id, text)
        if isinstance(outcome, TextSessionAppendAccepted):
            return _json(201, _message(outcome.message))
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


@router.get("/{session_id}")
def read_session(
    configuration: str, session_id: str,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> JSONResponse:
    agent = _agent(configuration, registry)
    return agent if isinstance(agent, JSONResponse) else agent.read(session_id)


@router.post("/{session_id}/messages", status_code=201)
async def append_message(
    configuration: str, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> JSONResponse:
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


def _message(value: TextMessage) -> dict[str, str]:
    result = {"role": value.role, "text": value.text}
    if value.turn_id is not None:
        result["turn_id"] = value.turn_id
    return result


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
