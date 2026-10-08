"""HTTP streaming of retained agent conversation activity."""

from collections.abc import AsyncIterator, Callable
from typing import TypeVar

from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.http_responses import artifact_response, snapshot_response
from app.sessions.models.conversation import ConversationReadActive
from app.sessions.models.history import TerminalRecord
from app.agents.models.http_streaming import (
    StreamClosing,
    StreamError,
    StreamEventPayload,
    StreamSnapshot,
    StreamTerminal,
    StreamUpsert,
)
from app.sessions.models.session import SessionReadExpired, SessionReadUnknown
from app.sessions.models.timeline import TimelineItem

ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)


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
                artifact.artifact_id: artifact_response(artifact)
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
            if terminal is not None and snapshot.active_turn_id != turn_id:
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


def _sse(event: StreamEventPayload) -> str:
    return f"data: {event.model_dump_json()}\n\n"
