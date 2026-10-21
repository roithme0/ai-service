"""Injectable native conversation HTTP boundary with caller-owned composition."""

import logging
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator
from starlette.types import Receive, Scope, Send

from app.agentic.config import MAX_PROMPT_CHARACTERS
from app.agentic.conversations import ConversationBusyError
from app.agentic.presentation import PresentedSession
from app.agentic.response import ResponseModel
from app.agentic.runner import AgentTurnRunner, RunnerClosedError
from app.agentic.sessions import (
    ObservationLimitError,
    ObservationOverflowError,
    SessionCreated,
    SessionNotFoundError,
)
from app.core.http_identity import require_application_user
from app.agentic.artifacts import ArtifactCapability
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


def _error(
    error: (
        SessionNotFoundError
        | ConversationBusyError
        | RunnerClosedError
        | ObservationLimitError
        | ValueError
    ),
) -> JSONResponse:
    if isinstance(error, SessionNotFoundError):
        status, kind = 404, BoundaryError(kind="unknown")
    elif isinstance(error, ConversationBusyError):
        status, kind = 409, BoundaryError(kind="busy")
    elif isinstance(error, RunnerClosedError):
        status, kind = 503, BoundaryError(kind="agent_unavailable")
    elif isinstance(error, ObservationLimitError):
        status, kind = 429, BoundaryError(kind="observation_limit")
    else:
        status, kind = 400, BoundaryError(kind="invalid_input")
    return JSONResponse(status_code=status, content=kind.model_dump())


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
    registry_provider: Callable[[], Mapping[str, AgentTurnRunner | None]],
) -> APIRouter:
    """Composition owns runner/agent lifetimes; routes stay on their event loop."""
    router = APIRouter(
        prefix="/api/v1/agents/{configuration}/sessions", tags=["agentic"]
    )

    def resolve(
        configuration: str, registry: Mapping[str, AgentTurnRunner | None]
    ) -> AgentTurnRunner | JSONResponse:
        if configuration not in registry:
            return JSONResponse(
                status_code=404,
                content=BoundaryError(kind="unknown_configuration").model_dump(),
            )
        return registry[configuration] or JSONResponse(
            status_code=503,
            content=BoundaryError(kind="agent_unavailable").model_dump(),
        )

    errors = {code: {"model": BoundaryError} for code in (400, 404, 409, 429, 503)}

    @router.post("", status_code=201, response_model=SessionCreated, responses=errors)
    async def create_session(
        configuration: str,
        body: SessionCreationRequest,
        owner: str = Depends(require_application_user),
        registry: Mapping[str, AgentTurnRunner | None] = Depends(registry_provider),
    ) -> SessionCreated | JSONResponse:
        runner = resolve(configuration, registry)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            return runner.create_session(
                owner=owner,
                initial_context=body.initial_context,
                artifact_capabilities=body.artifact_capabilities,
            )
        except (ValueError, RunnerClosedError) as error:
            return _error(error)

    @router.get("/{session_id}", response_model=PresentedSession, responses=errors)
    async def read_session(
        configuration: str,
        session_id: str,
        owner: str = Depends(require_application_user),
        registry: Mapping[str, AgentTurnRunner | None] = Depends(registry_provider),
    ) -> PresentedSession | JSONResponse:
        runner = resolve(configuration, registry)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            return runner.read_session(session_id, owner=owner)
        except SessionNotFoundError as error:
            return _error(error)

    @router.post(
        "/{session_id}/turns",
        status_code=202,
        response_model=TurnAccepted,
        responses=errors,
    )
    async def submit_prompt(
        configuration: str,
        session_id: str,
        body: PromptSubmissionRequest,
        owner: str = Depends(require_application_user),
        registry: Mapping[str, AgentTurnRunner | None] = Depends(registry_provider),
    ) -> TurnAccepted | JSONResponse:
        runner = resolve(configuration, registry)
        if isinstance(runner, JSONResponse):
            return runner
        try:
            await runner.submit(session_id, owner=owner, prompt=body.prompt)
        except (
            SessionNotFoundError,
            ConversationBusyError,
            RunnerClosedError,
        ) as error:
            return _error(error)
        return TurnAccepted()

    @router.get(
        "/{session_id}/events",
        response_class=EventStreamResponse,
        response_model=None,
        responses={
            **errors,
            200: {
                "model": RootModel[SessionEvent],
                "content": {"text/event-stream": {"schema": {"type": "object"}}},
            },
        },
    )
    async def observe_session(
        configuration: str,
        session_id: str,
        owner: str = Depends(require_application_user),
        registry: Mapping[str, AgentTurnRunner | None] = Depends(registry_provider),
    ) -> StreamingResponse | JSONResponse:
        runner = resolve(configuration, registry)
        if isinstance(runner, JSONResponse):
            return runner
        updates = runner.observe_session(session_id, owner=owner)
        try:
            first = await anext(updates)
        except (SessionNotFoundError, ObservationLimitError) as error:
            await updates.aclose()
            return _error(error)
        except BaseException:
            await updates.aclose()
            raise
        return _SessionEventResponse(first, updates)

    return router
