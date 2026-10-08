"""HTTP routes, adapters, and registry for configured agents."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Generic, TypeVar

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.agents.enums.configuration import AgentConfiguration
from app.agents.enums.runtime import RuntimeStatus
from app.agents.models.input import AgentInputRejected
from app.agents.service import ConfiguredAgentService
from app.agents.wiring import get_configured_agents
from app.agents.http_identity import require_application_user
from app.agents.models.context import ContextIssue
from app.sessions.models.conversation import ConversationReadActive
from app.agents.models.http_responses import (
    AcceptedTurnResponse,
    ErrorResponse,
    InputIssue,
    SessionCreationResponse,
    SessionSnapshotResponse,
    UserMessageResponse,
    ValidationErrorResponse,
)
from app.agents.models.http_requests import (
    EmptyTurnRequest,
    SessionCreationRequest,
    UserMessageRequest,
)
from app.agents.models.http_streaming import StreamEvent
from app.sessions.models.session import (
    SessionMessageAppendAccepted, SessionMessageAppendExpired,
    SessionMessageAppendInvalidMessage, SessionMessageAppendLimitReached,
    SessionMessageBusy, SessionReadExpired,
)
from app.agents.protocols.http import ConversationTransport
from app.agents.http_streaming import turn_event_stream
from app.agents.http_responses import (
    input_error_response, model_validation_details, session_error_response, snapshot_response,
    validation_error_response,
    user_message_response,
)

InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)
IssueT = TypeVar("IssueT")


@dataclass(frozen=True)
class AgentTransport(Generic[InputT, ContextT, PayloadT, IssueT]):
    agent: ConfiguredAgentService[InputT, ContextT, PayloadT, IssueT]
    input_from_json: Callable[[object], InputT]
    issue_from_domain: Callable[[IssueT], InputIssue]
    available: Callable[[], bool] = lambda: True

    def create(
        self, value: object, owner: str
    ) -> SessionCreationResponse | JSONResponse:
        if not self.available():
            return session_error_response("agent_unavailable")
        outcome = self.agent.create(self.input_from_json(value), owner)
        if isinstance(outcome, AgentInputRejected):
            return input_error_response(tuple(map(self.issue_from_domain, outcome.issues)))
        return SessionCreationResponse(
            session_id=outcome.session_id, expires_at=outcome.expires_at
        )

    def read(
        self, session_id: str, owner: str
    ) -> SessionSnapshotResponse | JSONResponse:
        if not self.agent.belongs_to(session_id, owner):
            return session_error_response("unknown")
        outcome = self.agent.read(session_id)
        if isinstance(outcome, ConversationReadActive):
            snapshot = outcome.snapshot
            return snapshot_response(snapshot)
        return session_error_response(
            "expired" if isinstance(outcome, SessionReadExpired) else "unknown"
        )

    def append(
        self, session_id: str, text: str, owner: str
    ) -> UserMessageResponse | JSONResponse:
        if not self.available():
            return session_error_response("agent_unavailable")
        if not self.agent.belongs_to(session_id, owner):
            return session_error_response("unknown")
        outcome = self.agent.append_user_message(session_id, text)
        if isinstance(outcome, SessionMessageAppendAccepted):
            return user_message_response(outcome.message)
        if isinstance(outcome, SessionMessageAppendExpired):
            return session_error_response("expired")
        if isinstance(outcome, SessionMessageAppendLimitReached):
            return session_error_response("limit_reached")
        if isinstance(outcome, SessionMessageAppendInvalidMessage):
            return input_error_response(
                (InputIssue(location=("text",), message="Invalid message"),),
                "invalid_message",
            )
        if isinstance(outcome, SessionMessageBusy):
            return session_error_response("busy")
        return session_error_response("unknown")

    def turn(self, session_id: str, owner: str) -> AcceptedTurnResponse | JSONResponse:
        if not self.available():
            return session_error_response("agent_unavailable")
        if not self.agent.belongs_to(session_id, owner):
            return session_error_response("unknown")
        outcome = self.agent.start_turn(session_id)
        if outcome.turn_id and outcome.kind in {
            "busy",
            "completed",
            "generation_failed",
            "conflict",
        }:
            return AcceptedTurnResponse(kind="accepted", turn_id=outcome.turn_id)
        return session_error_response(outcome.kind, outcome.turn_id)

    def observe(
        self, session_id: str, turn_id: str, owner: str
    ) -> StreamingResponse | JSONResponse:
        read = self.read(session_id, owner)
        if isinstance(read, JSONResponse):
            return read
        if not any(item.turn_id == turn_id for item in read.timeline):
            return session_error_response("unknown")
        if not self.agent.observation_available(session_id):
            return session_error_response("busy")

        return turn_event_stream(
            turn_id, self.agent.observe(session_id),
            lambda: self.agent.turn_terminal(session_id, turn_id),
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
        AgentTransport(kochwiki_agent, lambda value: value, _context_issue,
                       lambda: agents.kochwiki.status == RuntimeStatus.READY)
        if kochwiki_agent
        else None
    )
    demo: ConversationTransport | None = (
        AgentTransport(demo_agent, lambda value: value, _demo_issue,
                       lambda: agents.demo.status == RuntimeStatus.READY)
        if demo_agent
        else None
    )
    return {AgentConfiguration.KOCHWIKI: kochwiki, AgentConfiguration.DEMO: demo}


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


def _transport(
    configuration: str, registry: dict[str, ConversationTransport | None]
) -> ConversationTransport | JSONResponse:
    if configuration not in registry:
        return session_error_response("unknown_configuration")
    return registry[configuration] or session_error_response("agent_unavailable")


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


def create_session_router(
    registry_provider: Callable[[], dict[str, ConversationTransport | None]],
    configuration_names: tuple[str, ...],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/agents/{configuration}/sessions",
        tags=["agents"],
    )

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
        configuration: Annotated[str, Path(json_schema_extra={"enum": list(configuration_names)})],
        request: Request,
        owner: str = Depends(require_application_user),
        registry: dict[str, ConversationTransport | None] = Depends(registry_provider),
    ) -> SessionCreationResponse | JSONResponse:
        transport = _transport(configuration, registry)
        if isinstance(transport, JSONResponse):
            return transport
        try:
            body = SessionCreationRequest.model_validate(await _body(request))
        except ValidationError as error:
            return validation_error_response("invalid_input", model_validation_details(error))
        return transport.create(body.input, owner)

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
        configuration: Annotated[str, Path(json_schema_extra={"enum": list(configuration_names)})],
        session_id: str,
        owner: str = Depends(require_application_user),
        registry: dict[str, ConversationTransport | None] = Depends(registry_provider),
    ) -> SessionSnapshotResponse | JSONResponse:
        transport = _transport(configuration, registry)
        return transport if isinstance(transport, JSONResponse) else transport.read(session_id, owner)

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
        configuration: Annotated[str, Path(json_schema_extra={"enum": list(configuration_names)})],
        session_id: str,
        request: Request,
        owner: str = Depends(require_application_user),
        registry: dict[str, ConversationTransport | None] = Depends(registry_provider),
    ) -> UserMessageResponse | JSONResponse:
        transport = _transport(configuration, registry)
        if isinstance(transport, JSONResponse):
            return transport
        try:
            message = UserMessageRequest.model_validate(await _body(request))
        except ValidationError as error:
            return validation_error_response("invalid_message", model_validation_details(error))
        return transport.append(session_id, message.text, owner)

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
        configuration: Annotated[str, Path(json_schema_extra={"enum": list(configuration_names)})],
        session_id: str,
        request: Request,
        owner: str = Depends(require_application_user),
        registry: dict[str, ConversationTransport | None] = Depends(registry_provider),
    ) -> AcceptedTurnResponse | JSONResponse:
        transport = _transport(configuration, registry)
        if isinstance(transport, JSONResponse):
            return transport
        raw_body = await request.body()
        if raw_body:
            try:
                EmptyTurnRequest.model_validate(await _body(request))
            except ValidationError as error:
                return validation_error_response("invalid_input", model_validation_details(error))
        return transport.turn(session_id, owner)

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
        configuration: Annotated[str, Path(json_schema_extra={"enum": list(configuration_names)})],
        session_id: str,
        turn_id: str,
        owner: str = Depends(require_application_user),
        registry: dict[str, ConversationTransport | None] = Depends(registry_provider),
    ) -> StreamingResponse | JSONResponse:
        transport = _transport(configuration, registry)
        return (
            transport
            if isinstance(transport, JSONResponse)
            else transport.observe(session_id, turn_id, owner)
        )

    return router
