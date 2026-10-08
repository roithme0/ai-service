"""HTTP streaming of retained agent conversation activity."""

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import TypeVar

from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.http_responses import artifact_response, snapshot_response
from app.sessions.models.conversation import ConversationReadActive, ConversationSnapshot
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


@dataclass
class _StreamState:
    previous: dict[str, TimelineItem] = field(default_factory=dict)
    snapshot_sent: bool = False
    closing_sent: bool = False


def turn_event_stream(
    turn_id: str,
    updates: AsyncIterator[ConversationReadActive[ContextT, PayloadT] | SessionReadExpired | SessionReadUnknown | None],
    terminal_lookup: Callable[[], TerminalRecord | None],
) -> StreamingResponse:
    return StreamingResponse(
        _encode_events(_turn_events(turn_id, updates, terminal_lookup)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _turn_events(
    turn_id: str,
    updates: AsyncIterator[ConversationReadActive[ContextT, PayloadT] | SessionReadExpired | SessionReadUnknown | None],
    terminal_lookup: Callable[[], TerminalRecord | None],
) -> AsyncIterator[StreamEventPayload | None]:
    state = _StreamState()
    async for update in updates:
        if not isinstance(update, ConversationReadActive):
            yield StreamError(
                kind="error", turn_id=turn_id,
                reason="observation_limit" if update is None else "unavailable",
            )
            return
        snapshot = update.snapshot
        if not state.snapshot_sent:
            yield StreamSnapshot(kind="snapshot", turn_id=turn_id, snapshot=snapshot_response(snapshot))
            state.snapshot_sent = True
            state.previous = {_identity(item): item for item in snapshot.timeline}
            state.closing_sent = (
                snapshot.active_turn_id == turn_id and snapshot.active_turn_status == "closing"
            )
        else:
            for event in _timeline_upserts(turn_id, snapshot, state.previous):
                yield event
        if (
            not state.closing_sent
            and snapshot.active_turn_id == turn_id
            and snapshot.active_turn_status == "closing"
        ):
            yield StreamClosing(kind="closing", turn_id=turn_id, sequence=snapshot.sequence)
            state.closing_sent = True
        terminal = terminal_lookup()
        if terminal is not None and snapshot.active_turn_id != turn_id:
            yield StreamTerminal(
                kind="terminal", turn_id=turn_id, sequence=snapshot.sequence, outcome=terminal.kind,
            )
            return
        yield None


def _timeline_upserts(
    turn_id: str,
    snapshot: ConversationSnapshot[ContextT, PayloadT],
    previous: dict[str, TimelineItem],
) -> Iterator[StreamUpsert]:
    artifacts = {
        artifact.artifact_id: artifact_response(artifact)
        for artifact in snapshot.artifacts
    }
    for order, item in enumerate(snapshot.timeline):
        identity = _identity(item)
        if item.turn_id == turn_id and previous.get(identity) != item:
            yield StreamUpsert(
                kind="upsert", turn_id=turn_id, identity=identity, order=order,
                sequence=snapshot.sequence, item=item,
                artifact=artifacts.get(item.artifact_id) if item.kind == "artifact" else None,
            )
        previous[identity] = item


async def _encode_events(events: AsyncIterator[StreamEventPayload | None]) -> AsyncIterator[str]:
    async for event in events:
        yield ": heartbeat\n\n" if event is None else _sse(event)


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
