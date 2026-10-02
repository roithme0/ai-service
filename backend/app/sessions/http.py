"""HTTP boundary for configured conversation agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, Literal, Protocol, TypeVar

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer

from app.agents.wiring import get_configured_agents
from app.sessions.context import ContextIssue
from app.sessions.agent_service import AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationMessageBusy, ConversationReadActive, StagedArtifact, TurnKind
from app.sessions.text_sessions import (
    TextMessage, TextSessionAppendAccepted, TextSessionAppendExpired,
    TextSessionAppendInvalidMessage, TextSessionAppendLimitReached,
    TextSessionReadExpired,
)


router = APIRouter(prefix="/api/v1/agents/{configuration}/sessions", tags=["agents"])


class AgentConfiguration(StrEnum):
    DEMO = "demo"
    KOCHWIKI = "kochwiki"


ConfigurationPath = Annotated[
    str, Path(json_schema_extra={"enum": [configuration.value for configuration in AgentConfiguration]})
]


InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)
IssueT = TypeVar("IssueT")


class InputIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    location: tuple[str | int, ...]
    message: str


SessionErrorKind = Literal[
    "unknown_configuration", "agent_unavailable", "unknown", "expired", "busy",
    "not_ready", "conflict", "limit_reached", "generation_failed",
]

ErrorKind = Literal[
    "not_found", SessionErrorKind, "method_not_allowed", "http_error", "internal_error",
]


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    detail: str = Field(min_length=1)
    kind: ErrorKind
    turn_id: str | None = None


class ValidationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    loc: tuple[str | int, ...] = Field(min_length=1)
    msg: str = Field(min_length=1)
    type: str = Field(min_length=1)


class ValidationErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    detail: list[ValidationDetail] = Field(min_length=1)
    kind: Literal["invalid_input", "invalid_message", "request_validation"]


class SessionCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input: object = None


class UserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class EmptyTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
            return _input_error((InputIssue(location=("text",), message="Invalid message"),), "invalid_message")
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


def _context_issue(issue: ContextIssue) -> InputIssue:
    return InputIssue(location=("input", *issue.location), message=issue.message)


def _demo_issue(issue: str) -> InputIssue:
    return InputIssue(location=("input",), message=issue)


def get_agent_registry() -> dict[str, ConversationTransport | None]:
    agents = get_configured_agents()
    kochwiki_agent = agents.kochwiki.agent
    demo_agent = agents.demo.agent
    kochwiki: ConversationTransport | None = (
        AgentTransport(kochwiki_agent, lambda value: value, _context_issue) if kochwiki_agent else None
    )
    demo: ConversationTransport | None = (
        AgentTransport(demo_agent, lambda value: value, _demo_issue) if demo_agent else None
    )
    return {AgentConfiguration.KOCHWIKI: kochwiki, AgentConfiguration.DEMO: demo}


def _agent(configuration: str, registry: dict[str, ConversationTransport | None]) -> ConversationTransport | JSONResponse:
    if configuration not in registry:
        return _error("unknown_configuration")
    return registry[configuration] or _error("agent_unavailable")


async def _body(request: Request) -> object:
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        return None


def _request_body(model: type[BaseModel], *, required: bool = True) -> dict[str, object]:
    return {"requestBody": {
        "required": required,
        "content": {"application/json": {"schema": model.model_json_schema(mode="validation")}},
    }}


@router.post("", status_code=201, response_model=SessionCreationResponse, responses={
    404: {"model": ErrorResponse},
    422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
    503: {"model": ErrorResponse},
}, openapi_extra=_request_body(SessionCreationRequest))
async def create_session(
    configuration: ConfigurationPath, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionCreationResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    try:
        body = SessionCreationRequest.model_validate(await _body(request))
    except ValidationError as error:
        return _validation_error("invalid_input", _model_validation_details(error))
    return agent.create(body.input)


@router.get("/{session_id}", response_model=SessionSnapshotResponse, responses={
    404: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
    503: {"model": ErrorResponse},
})
def read_session(
    configuration: ConfigurationPath, session_id: str,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionSnapshotResponse | JSONResponse:
    agent = _agent(configuration, registry)
    return agent if isinstance(agent, JSONResponse) else agent.read(session_id)


@router.post("/{session_id}/messages", status_code=201, response_model=UserMessageResponse, responses={
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
    503: {"model": ErrorResponse},
}, openapi_extra=_request_body(UserMessageRequest))
async def append_message(
    configuration: ConfigurationPath, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> UserMessageResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    try:
        message = UserMessageRequest.model_validate(await _body(request))
    except ValidationError as error:
        return _validation_error("invalid_message", _model_validation_details(error))
    return agent.append(session_id, message.text)


@router.post("/{session_id}/turns", status_code=201, response_model=CompletedTurnResponse, responses={
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
    422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}, openapi_extra=_request_body(EmptyTurnRequest, required=False))
async def execute_turn(
    configuration: ConfigurationPath, session_id: str, request: Request,
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> CompletedTurnResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    raw_body = await request.body()
    if raw_body:
        try:
            EmptyTurnRequest.model_validate(await _body(request))
        except ValidationError as error:
            return _validation_error("invalid_input", _model_validation_details(error))
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


def _model_validation_details(error: ValidationError) -> list[ValidationDetail]:
    return [ValidationDetail(
        loc=("body", *issue["loc"]),
        msg=(
            "request must be an object" if issue["type"] == "model_type"
            else "extra field not permitted" if issue["type"] == "extra_forbidden"
            else issue["msg"]
        ),
        type=issue["type"],
    ) for issue in error.errors()]


def _validation_error(
    kind: Literal["invalid_input", "invalid_message", "request_validation"],
    detail: list[ValidationDetail],
) -> JSONResponse:
    return _json(422, ValidationErrorResponse(detail=detail, kind=kind))


def _input_error(
    issues: tuple[InputIssue, ...], kind: Literal["invalid_input", "invalid_message"] = "invalid_input"
) -> JSONResponse:
    return _validation_error(kind, [
        ValidationDetail(loc=("body", *issue.location), msg=issue.message, type="value_error")
        for issue in issues
    ])


def _error(kind: SessionErrorKind, turn_id: str | None = None) -> JSONResponse:
    responses: dict[SessionErrorKind, tuple[int, str]] = {
        "unknown_configuration": (404, "Agent configuration not found"),
        "agent_unavailable": (503, "Agent unavailable"),
        "unknown": (404, "Session not found"),
        "expired": (410, "Session expired"),
        "busy": (409, "Session is busy"),
        "not_ready": (409, "Session is not ready for a turn"),
        "conflict": (409, "Session state changed during the turn"),
        "limit_reached": (409, "Session limit reached"),
        "generation_failed": (502, "Turn generation failed"),
    }
    status, detail = responses[kind]
    return _json(status, ErrorResponse(detail=detail, kind=kind, turn_id=turn_id or None))


def _json(status: int, content: ErrorResponse | ValidationErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status, content=content.model_dump(mode="json", exclude_none=True))
