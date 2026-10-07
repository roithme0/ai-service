"""HTTP boundary for configured conversation agents."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.agents.wiring import get_configured_agents
from app.core.models import ValidationDetail
from app.sessions.models.context import ContextIssue
from app.sessions.models.http import (
    AcceptedTurnResponse,
    ArtifactResponse,
    AssistantMessageResponse,
    EmptyTurnRequest,
    ErrorResponse,
    InputIssue,
    SessionCreationRequest,
    SessionCreationResponse,
    SessionErrorKind,
    SessionSnapshotResponse,
    StreamClosing,
    StreamError,
    StreamEvent,
    StreamSnapshot,
    StreamTerminal,
    StreamUpsert,
    UserMessageRequest,
    UserMessageResponse,
    ValidationErrorKind,
    ValidationErrorResponse,
)
from app.sessions.protocols.http import ConversationTransport
from app.sessions.identity import require_application_user
from app.agents.models.input import AgentInputRejected
from app.agents.service import ConfiguredAgentService
from app.sessions.models.conversation import (
    ConversationMessageBusy,
    ConversationReadActive,
)
from app.sessions.models.artifacts import PublishedArtifact
from app.sessions.models.timeline import TimelineItem, TimelineMessage
from app.sessions.models.session import (
    TextMessage,
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionAppendInvalidMessage,
    TextSessionAppendLimitReached,
    TextSessionReadExpired,
)

router = APIRouter(
    prefix="/api/v1/agents/{configuration}/sessions",
    tags=["agents"],
)


class AgentConfiguration(StrEnum):
    DEMO = "demo"
    KOCHWIKI = "kochwiki"


ConfigurationPath = Annotated[
    str,
    Path(
        json_schema_extra={
            "enum": [configuration.value for configuration in AgentConfiguration]
        }
    ),
]


InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)
IssueT = TypeVar("IssueT")


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


@dataclass(frozen=True)
class AgentTransport(Generic[InputT, ContextT, PayloadT, IssueT]):
    agent: ConfiguredAgentService[InputT, ContextT, PayloadT, IssueT]
    input_from_json: Callable[[object], InputT]
    issue_from_domain: Callable[[IssueT], InputIssue]

    def create(
        self, value: object, owner: str
    ) -> SessionCreationResponse | JSONResponse:
        outcome = self.agent.create(self.input_from_json(value), owner)
        if isinstance(outcome, AgentInputRejected):
            return _input_error(tuple(map(self.issue_from_domain, outcome.issues)))
        return SessionCreationResponse(
            session_id=outcome.session_id, expires_at=outcome.expires_at
        )

    def read(
        self, session_id: str, owner: str
    ) -> SessionSnapshotResponse | JSONResponse:
        if not self.agent.belongs_to(session_id, owner):
            return _error("unknown")
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
                timeline=list(snapshot.timeline),
                active_turn_id=snapshot.active_turn_id,
                active_turn_status=snapshot.active_turn_status,
                sequence=snapshot.sequence,
            )
        return _error(
            "expired" if isinstance(outcome, TextSessionReadExpired) else "unknown"
        )

    def append(
        self, session_id: str, text: str, owner: str
    ) -> UserMessageResponse | JSONResponse:
        if not self.agent.belongs_to(session_id, owner):
            return _error("unknown")
        outcome = self.agent.append_user_message(session_id, text)
        if isinstance(outcome, TextSessionAppendAccepted):
            return _user_message(outcome.message)
        if isinstance(outcome, TextSessionAppendExpired):
            return _error("expired")
        if isinstance(outcome, TextSessionAppendLimitReached):
            return _error("limit_reached")
        if isinstance(outcome, TextSessionAppendInvalidMessage):
            return _input_error(
                (InputIssue(location=("text",), message="Invalid message"),),
                "invalid_message",
            )
        if isinstance(outcome, ConversationMessageBusy):
            return _error("busy")
        return _error("unknown")

    def turn(self, session_id: str, owner: str) -> AcceptedTurnResponse | JSONResponse:
        if not self.agent.belongs_to(session_id, owner):
            return _error("unknown")
        outcome = self.agent.start_turn(session_id)
        if outcome.turn_id and outcome.kind in {
            "busy",
            "completed",
            "generation_failed",
            "conflict",
        }:
            return AcceptedTurnResponse(kind="accepted", turn_id=outcome.turn_id)
        return _error(outcome.kind, outcome.turn_id)

    def observe(
        self, session_id: str, turn_id: str, owner: str
    ) -> StreamingResponse | JSONResponse:
        read = self.read(session_id, owner)
        if isinstance(read, JSONResponse):
            return read
        if not any(item.turn_id == turn_id for item in read.timeline):
            return _error("unknown")
        if not self.agent.observation_available(session_id):
            return _error("busy")

        async def events() -> AsyncIterator[str]:
            previous: dict[str, TimelineItem] = {}
            initial = True
            closing_sent = False
            async for update in self.agent.observe(session_id):
                if update is None or not isinstance(update, ConversationReadActive):
                    yield _sse(
                        StreamError(
                            kind="error",
                            turn_id=turn_id,
                            reason=(
                                "observation_limit" if update is None else "unavailable"
                            ),
                        )
                    )
                    return
                snapshot = update.snapshot
                artifacts = {
                    artifact.artifact_id: _artifact(artifact)
                    for artifact in snapshot.artifacts
                }
                if initial:
                    public = SessionSnapshotResponse(
                        session_id=session_id,
                        expires_at=snapshot.session.expires_at,
                        messages=[
                            _message(message) for message in snapshot.session.messages
                        ],
                        artifacts=list(artifacts.values()),
                        terminal_turn_id=snapshot.terminal_turn_id,
                        terminal_turn_kind=snapshot.terminal_turn_kind,
                        timeline=list(snapshot.timeline),
                        active_turn_id=snapshot.active_turn_id,
                        sequence=snapshot.sequence,
                        active_turn_status=snapshot.active_turn_status,
                    )
                    yield _sse(
                        StreamSnapshot(
                            kind="snapshot", turn_id=turn_id, snapshot=public
                        )
                    )
                    initial = False
                    previous = {_identity(item): item for item in snapshot.timeline}
                    closing_sent = (
                        snapshot.active_turn_id == turn_id
                        and snapshot.active_turn_status == "closing"
                    )
                for order, item in enumerate(snapshot.timeline):
                    identity = _identity(item)
                    if item.turn_id == turn_id and previous.get(identity) != item:
                        yield _sse(
                            StreamUpsert(
                                kind="upsert",
                                turn_id=turn_id,
                                identity=identity,
                                order=order,
                                sequence=snapshot.sequence,
                                item=item,
                                artifact=(
                                    artifacts.get(item.artifact_id)
                                    if item.kind == "artifact"
                                    else None
                                ),
                            )
                        )
                    previous[identity] = item
                if (
                    not closing_sent
                    and snapshot.active_turn_id == turn_id
                    and snapshot.active_turn_status == "closing"
                ):
                    yield _sse(
                        StreamClosing(
                            kind="closing", turn_id=turn_id, sequence=snapshot.sequence
                        )
                    )
                    closing_sent = True
                terminal = self.agent.turn_terminal(session_id, turn_id)
                if terminal is not None:
                    if snapshot.active_turn_id != turn_id:
                        yield _sse(
                            StreamTerminal(
                                kind="terminal",
                                turn_id=turn_id,
                                sequence=snapshot.sequence,
                                outcome=terminal.kind,
                            )
                        )
                        return
                yield ": heartbeat\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


def _context_issue(issue: ContextIssue) -> InputIssue:
    return InputIssue(location=("input", *issue.location), message=issue.message)


def _demo_issue(issue: str) -> InputIssue:
    return InputIssue(location=("input",), message=issue)


def get_agent_registry() -> dict[str, ConversationTransport | None]:
    agents = get_configured_agents()
    kochwiki_agent = agents.kochwiki.agent
    demo_agent = agents.demo.agent
    kochwiki: ConversationTransport | None = (
        AgentTransport(kochwiki_agent, lambda value: value, _context_issue)
        if kochwiki_agent
        else None
    )
    demo: ConversationTransport | None = (
        AgentTransport(demo_agent, lambda value: value, _demo_issue)
        if demo_agent
        else None
    )
    return {AgentConfiguration.KOCHWIKI: kochwiki, AgentConfiguration.DEMO: demo}


def _agent(
    configuration: str, registry: dict[str, ConversationTransport | None]
) -> ConversationTransport | JSONResponse:
    if configuration not in registry:
        return _error("unknown_configuration")
    return registry[configuration] or _error("agent_unavailable")


async def _body(request: Request) -> object:
    try:
        return await request.json()
    except (ValueError, UnicodeDecodeError):
        return None


def _request_body(
    model: type[BaseModel], *, required: bool = True
) -> dict[str, object]:
    return {
        "requestBody": {
            "required": required,
            "content": {
                "application/json": {
                    "schema": model.model_json_schema(mode="validation")
                }
            },
        }
    }


@router.post(
    "",
    status_code=201,
    response_model=SessionCreationResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
        503: {"model": ErrorResponse},
    },
    openapi_extra=_request_body(SessionCreationRequest),
)
async def create_session(
    configuration: ConfigurationPath,
    request: Request,
    owner: str = Depends(require_application_user),
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionCreationResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    try:
        body = SessionCreationRequest.model_validate(await _body(request))
    except ValidationError as error:
        return _validation_error("invalid_input", _model_validation_details(error))
    return agent.create(body.input, owner)


@router.get(
    "/{session_id}",
    response_model=SessionSnapshotResponse,
    responses={
        404: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
        503: {"model": ErrorResponse},
    },
)
def read_session(
    configuration: ConfigurationPath,
    session_id: str,
    owner: str = Depends(require_application_user),
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> SessionSnapshotResponse | JSONResponse:
    agent = _agent(configuration, registry)
    return agent if isinstance(agent, JSONResponse) else agent.read(session_id, owner)


@router.post(
    "/{session_id}/messages",
    status_code=201,
    response_model=UserMessageResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
        503: {"model": ErrorResponse},
    },
    openapi_extra=_request_body(UserMessageRequest),
)
async def append_message(
    configuration: ConfigurationPath,
    session_id: str,
    request: Request,
    owner: str = Depends(require_application_user),
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> UserMessageResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    try:
        message = UserMessageRequest.model_validate(await _body(request))
    except ValidationError as error:
        return _validation_error("invalid_message", _model_validation_details(error))
    return agent.append(session_id, message.text, owner)


@router.post(
    "/{session_id}/turns",
    status_code=202,
    response_model=AcceptedTurnResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    openapi_extra=_request_body(EmptyTurnRequest, required=False),
)
async def execute_turn(
    configuration: ConfigurationPath,
    session_id: str,
    request: Request,
    owner: str = Depends(require_application_user),
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> AcceptedTurnResponse | JSONResponse:
    agent = _agent(configuration, registry)
    if isinstance(agent, JSONResponse):
        return agent
    raw_body = await request.body()
    if raw_body:
        try:
            EmptyTurnRequest.model_validate(await _body(request))
        except ValidationError as error:
            return _validation_error("invalid_input", _model_validation_details(error))
    return agent.turn(session_id, owner)


@router.get(
    "/{session_id}/turns/{turn_id}/events",
    response_class=EventStreamResponse,
    response_model=None,
    responses={
        200: {"model": StreamEvent},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        410: {"model": ErrorResponse},
        422: {"model": ValidationErrorResponse, "description": "Unprocessable Content"},
    },
)
def observe_turn(
    configuration: ConfigurationPath,
    session_id: str,
    turn_id: str,
    owner: str = Depends(require_application_user),
    registry: dict[str, ConversationTransport | None] = Depends(get_agent_registry),
) -> StreamingResponse | JSONResponse:
    agent = _agent(configuration, registry)
    return (
        agent
        if isinstance(agent, JSONResponse)
        else agent.observe(session_id, turn_id, owner)
    )


def _identity(item: TimelineItem) -> str:
    if item.kind in {"message", "intermediate"}:
        return item.id
    if item.kind == "tool":
        return f"tool-{item.execution_id}"
    if item.kind == "artifact":
        return item.artifact_id
    return f"failure-{item.turn_id}"


def _sse(
    event: StreamSnapshot | StreamUpsert | StreamClosing | StreamTerminal | StreamError,
) -> str:
    return f"data: {event.model_dump_json()}\n\n"


def _user_message(value: TextMessage) -> UserMessageResponse:
    return UserMessageResponse.model_validate(
        {"role": value.role, "text": value.text, "turn_id": value.turn_id}
    )


def _message(value: TextMessage) -> UserMessageResponse | AssistantMessageResponse:
    if value.role == "user":
        return _user_message(value)
    return AssistantMessageResponse.model_validate(
        {"role": value.role, "text": value.text, "turn_id": value.turn_id}
    )


def _artifact(value: PublishedArtifact[PayloadT]) -> ArtifactResponse:
    return ArtifactResponse(
        artifact_id=value.artifact_id,
        type=value.type,
        created_at=value.created_at,
        order=value.order,
        turn_id=value.turn_id,
        payload=value.payload.model_dump(mode="json"),
    )


def _model_validation_details(error: ValidationError) -> list[ValidationDetail]:
    return [
        ValidationDetail(
            loc=("body", *issue["loc"]),
            msg=(
                "request must be an object"
                if issue["type"] == "model_type"
                else (
                    "extra field not permitted"
                    if issue["type"] == "extra_forbidden"
                    else issue["msg"]
                )
            ),
            type=issue["type"],
        )
        for issue in error.errors()
    ]


def _validation_error(
    kind: ValidationErrorKind,
    detail: list[ValidationDetail],
) -> JSONResponse:
    return _json(422, ValidationErrorResponse(detail=detail, kind=kind))


def _input_error(
    issues: tuple[InputIssue, ...],
    kind: Literal["invalid_input", "invalid_message"] = "invalid_input",
) -> JSONResponse:
    return _validation_error(
        kind,
        [
            ValidationDetail(
                loc=("body", *issue.location), msg=issue.message, type="value_error"
            )
            for issue in issues
        ],
    )


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
    return _json(
        status, ErrorResponse(detail=detail, kind=kind, turn_id=turn_id or None)
    )


def _json(
    status: int, content: ErrorResponse | ValidationErrorResponse
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=content.model_dump(mode="json", exclude_none=True)
    )
