"""Session HTTP response conversion and turn event streaming."""

from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from app.core.models import ValidationDetail
from app.sessions.models.artifacts import PublishedArtifact
from app.sessions.models.conversation import ConversationReadActive, ConversationSnapshot
from app.sessions.models.history import TerminalRecord
from app.sessions.models.http import (
    ArtifactResponse, AssistantMessageResponse, ErrorResponse,
    InputIssue, InputValidationErrorKind, SessionErrorKind, SessionSnapshotResponse,
    StreamClosing, StreamError, StreamSnapshot, StreamTerminal, StreamUpsert,
    UserMessageResponse, ValidationErrorKind, ValidationErrorResponse,
)
from app.sessions.models.session import SessionReadExpired, SessionReadUnknown, TextMessage
from app.sessions.models.timeline import TimelineItem

ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)


def snapshot_response(
    snapshot: ConversationSnapshot[ContextT, PayloadT],
) -> SessionSnapshotResponse:
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


def turn_event_stream(
    turn_id: str,
    updates: AsyncIterator[ConversationReadActive[ContextT, PayloadT] | SessionReadExpired | SessionReadUnknown | None],
    terminal_lookup: Callable[[], TerminalRecord | None],
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        previous: dict[str, TimelineItem] = {}
        initial = True
        closing_sent = False
        async for update in updates:
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
                public = snapshot_response(snapshot)
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
            terminal = terminal_lookup()
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


def user_message_response(value: TextMessage) -> UserMessageResponse:
    return UserMessageResponse.model_validate(
        {"role": value.role, "text": value.text, "turn_id": value.turn_id}
    )


def _message(value: TextMessage) -> UserMessageResponse | AssistantMessageResponse:
    if value.role == "user":
        return user_message_response(value)
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


def model_validation_details(error: ValidationError) -> list[ValidationDetail]:
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


def validation_error_response(
    kind: ValidationErrorKind,
    detail: list[ValidationDetail],
) -> JSONResponse:
    return _json(422, ValidationErrorResponse(detail=detail, kind=kind))


def input_error_response(
    issues: tuple[InputIssue, ...],
    kind: InputValidationErrorKind = "invalid_input",
) -> JSONResponse:
    return validation_error_response(
        kind,
        [
            ValidationDetail(
                loc=("body", *issue.location), msg=issue.message, type="value_error"
            )
            for issue in issues
        ],
    )


def session_error_response(kind: SessionErrorKind, turn_id: str | None = None) -> JSONResponse:
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
