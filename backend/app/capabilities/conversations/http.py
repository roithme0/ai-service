"""Injectable native conversation HTTP boundary with caller-owned composition."""

import logging
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator
from starlette.types import Receive, Scope, Send

from app.capabilities.conversations.config import MAX_PROMPT_CHARACTERS
from app.capabilities.conversations.limits import ConversationLimitReached
from app.capabilities.conversations.session_state import SessionBusyError
from app.capabilities.conversations.presentation import PresentedSession
from app.capabilities.conversations.response import ResponseModel
from app.capabilities.conversations.runner import AgentTurnRunner, RunnerClosedError
from app.capabilities.conversations.sessions import (
    ObservationLimitError,
    ObservationOverflowError,
    SessionCreated,
    SessionNotFoundError,
)
from app.core.http import require_application_user
from app.core.identity import ApplicationIdentity
from app.capabilities.conversations.artifacts import ArtifactCapability
from app.core.json import FiniteJsonValue

_logger = logging.getLogger(__name__)


class SessionCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    initial_context: dict[str, FiniteJsonValue] | None = None
    artifact_capabilities: list[ArtifactCapability] = Field(default_factory=list)


class PromptSubmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARACTERS)

    @field_validator("prompt")
    @classmethod
    def nonblank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must not be blank.")
        return value


class TurnAccepted(ResponseModel):
    kind: Literal["accepted"] = "accepted"


class BoundaryError(ResponseModel):
    kind: Literal[
        "unknown_configuration",
        "unknown",
        "busy",
        "agent_unavailable",
        "invalid_input",
        "observation_limit",
        "conversation_limit_reached",
    ]


class SnapshotEvent(ResponseModel):
    kind: Literal["snapshot"] = "snapshot"
    snapshot: PresentedSession


class ObservationErrorEvent(ResponseModel):
    kind: Literal["error"] = "error"
    reason: Literal[
        "unknown", "observation_overflow", "internal_error"
    ]


type SessionEvent = Annotated[
    SnapshotEvent | ObservationErrorEvent, Field(discriminator="kind")
]


def _error_response(
    error: (
        SessionNotFoundError
        | ConversationLimitReached
        | SessionBusyError
        | RunnerClosedError
        | ObservationLimitError
        | ValueError
    ),
) -> JSONResponse:
    match error:
        case SessionNotFoundError():
            status_code, body = 404, BoundaryError(kind="unknown")
        case ConversationLimitReached():
            status_code, body = 409, BoundaryError(kind="conversation_limit_reached")
        case SessionBusyError():
            status_code, body = 409, BoundaryError(kind="busy")
        case RunnerClosedError():
            status_code, body = 503, BoundaryError(kind="agent_unavailable")
        case ObservationLimitError():
            status_code, body = 429, BoundaryError(kind="observation_limit")
        case _:
            status_code, body = 400, BoundaryError(kind="invalid_input")
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def _events(
    first: PresentedSession,
    updates: AsyncGenerator[PresentedSession, None],
) -> AsyncGenerator[str, None]:
    yield f"data: {SnapshotEvent(snapshot=first).model_dump_json()}\n\n"
    try:
        async for snapshot in updates:
            yield f"data: {SnapshotEvent(snapshot=snapshot).model_dump_json()}\n\n"
    except SessionNotFoundError:
        yield f"data: {ObservationErrorEvent(reason='unknown').model_dump_json()}\n\n"
    except ObservationOverflowError:
        yield f"data: {ObservationErrorEvent(reason='observation_overflow').model_dump_json()}\n\n"
    except Exception as error:
        _logger.error("Session observation failed (%s).", type(error).__name__)
        yield f"data: {ObservationErrorEvent(reason='internal_error').model_dump_json()}\n\n"


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


class _SessionEventResponse(EventStreamResponse):
    def __init__(
        self, first: PresentedSession, updates: AsyncGenerator[PresentedSession, None]
    ) -> None:
        self._updates = updates
        self._events = _events(first, updates)
        super().__init__(
            self._events,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._events.aclose()
            await self._updates.aclose()


def create_session_router(
    runners_provider: Callable[[], Mapping[str, AgentTurnRunner | None]],
) -> APIRouter:
    """Composition owns runner/agent lifetimes; routes stay on their event loop."""
    router = APIRouter(
        prefix="/api/v1/agents/{configuration}/sessions", tags=["conversations"]
    )

    def resolve_runner(
        configuration: str, runners: Mapping[str, AgentTurnRunner | None]
    ) -> AgentTurnRunner | JSONResponse:
        if configuration not in runners:
            return JSONResponse(
                status_code=404,
                content=BoundaryError(kind="unknown_configuration").model_dump(),
            )
        return runners[configuration] or JSONResponse(
            status_code=503,
            content=BoundaryError(kind="agent_unavailable").model_dump(),
        )

    @router.post(
        "",
        status_code=201,
        response_model=SessionCreated,
        responses={code: {"model": BoundaryError} for code in (400, 404, 503)},
    )
    async def create_session(
        configuration: str,
        body: SessionCreationRequest,
        owner: ApplicationIdentity = Depends(require_application_user),
        runners: Mapping[str, AgentTurnRunner | None] = Depends(runners_provider),
    ) -> SessionCreated | JSONResponse:
        runner = resolve_runner(configuration, runners)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            return runner.create_session(
                owner=owner,
                initial_context=body.initial_context,
                artifact_capabilities=body.artifact_capabilities,
            )
        except (ValueError, RunnerClosedError) as error:
            return _error_response(error)

    @router.get(
        "/{session_id}",
        response_model=PresentedSession,
        responses={code: {"model": BoundaryError} for code in (404, 503)},
    )
    async def read_session(
        configuration: str,
        session_id: str,
        owner: ApplicationIdentity = Depends(require_application_user),
        runners: Mapping[str, AgentTurnRunner | None] = Depends(runners_provider),
    ) -> PresentedSession | JSONResponse:
        runner = resolve_runner(configuration, runners)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            return runner.read_session(session_id, owner=owner)
        except SessionNotFoundError as error:
            return _error_response(error)

    @router.post(
        "/{session_id}/turns",
        status_code=202,
        response_model=TurnAccepted,
        responses={code: {"model": BoundaryError} for code in (404, 409, 503)},
    )
    async def submit_prompt(
        configuration: str,
        session_id: str,
        body: PromptSubmissionRequest,
        owner: ApplicationIdentity = Depends(require_application_user),
        runners: Mapping[str, AgentTurnRunner | None] = Depends(runners_provider),
    ) -> TurnAccepted | JSONResponse:
        runner = resolve_runner(configuration, runners)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            await runner.submit(session_id, owner=owner, prompt=body.prompt)
        except (
            SessionNotFoundError,
            SessionBusyError,
            ConversationLimitReached,
            RunnerClosedError,
        ) as error:
            return _error_response(error)
        return TurnAccepted()

    @router.get(
        "/{session_id}/events",
        response_class=EventStreamResponse,
        response_model=None,
        responses={
            **{code: {"model": BoundaryError} for code in (404, 429, 503)},
            200: {
                "model": RootModel[SessionEvent],
                "content": {"text/event-stream": {"schema": {"type": "object"}}},
            },
        },
    )
    async def observe_session(
        configuration: str,
        session_id: str,
        owner: ApplicationIdentity = Depends(require_application_user),
        runners: Mapping[str, AgentTurnRunner | None] = Depends(runners_provider),
    ) -> StreamingResponse | JSONResponse:
        runner = resolve_runner(configuration, runners)
        if isinstance(runner, JSONResponse):
            return runner
        updates = runner.observe_session(session_id, owner=owner)
        try:
            first = await anext(updates)
        except (SessionNotFoundError, ObservationLimitError) as error:
            await updates.aclose()
            return _error_response(error)
        except BaseException:
            await updates.aclose()
            raise
        return _SessionEventResponse(first, updates)

    return router
