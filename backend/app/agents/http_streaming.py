"""HTTP streaming of retained agent conversation activity."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import TypeVar

from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.http_responses import timeline_item_response, snapshot_response
from app.sessions.models.conversation import ConversationReadActive
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
from app.sessions.models.turns import TurnSnapshot

ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)


@dataclass
class _StreamState[PayloadT]:
    previous: dict[str, TimelineItem[PayloadT]] = field(default_factory=dict)
    snapshot_sent: bool = False
    closing_sent: bool = False


def turn_event_stream(
    turn_id: str,
    updates: AsyncIterator[ConversationReadActive[ContextT, PayloadT] | SessionReadExpired | SessionReadUnknown | None],
) -> StreamingResponse:
    return StreamingResponse(
        _encode_events(_turn_events(turn_id, updates)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _turn_events(
    turn_id: str,
    updates: AsyncIterator[ConversationReadActive[ContextT, PayloadT] | SessionReadExpired | SessionReadUnknown | None],
) -> AsyncIterator[StreamEventPayload | None]:
    state = _StreamState[PayloadT]()
    async for update in updates:
        if not isinstance(update, ConversationReadActive):
            yield StreamError(
                kind="error", turn_id=turn_id,
                reason="observation_limit" if update is None else "unavailable",
            )
            return
        snapshot = update.snapshot
        turn = next((turn for turn in snapshot.turns if turn.turn_id == turn_id), None)
        if turn is None:
            yield StreamError(kind="error", turn_id=turn_id, reason="unavailable")
            return
        if not state.snapshot_sent:
            yield StreamSnapshot(kind="snapshot", turn_id=turn_id, snapshot=snapshot_response(snapshot))
            state.snapshot_sent = True
            state.previous = {_identity(item): item for item in turn.timeline}
            state.closing_sent = turn.status == "closing"
        else:
            for event in _timeline_upserts(turn, snapshot.sequence, state.previous):
                yield event
        if not state.closing_sent and turn.status == "closing":
            yield StreamClosing(kind="closing", turn_id=turn_id, sequence=snapshot.sequence)
            state.closing_sent = True
        if turn.status in {"completed", "generation_failed", "conflict"}:
            yield StreamTerminal(
                kind="terminal", turn_id=turn_id, sequence=snapshot.sequence, outcome=turn.status,
            )
            return
        yield None


def _timeline_upserts(
    turn: TurnSnapshot[PayloadT],
    sequence: int,
    previous: dict[str, TimelineItem[PayloadT]],
) -> Iterator[StreamUpsert]:
    for order, item in enumerate(turn.timeline):
        identity = _identity(item)
        if previous.get(identity) != item:
            yield StreamUpsert(
                kind="upsert", turn_id=turn.turn_id, identity=identity, order=order,
                sequence=sequence, item=timeline_item_response(item),
            )
        previous[identity] = item


async def _encode_events(events: AsyncIterator[StreamEventPayload | None]) -> AsyncIterator[str]:
    async for event in events:
        yield ": heartbeat\n\n" if event is None else _sse(event)


def _identity(item: TimelineItem[PayloadT]) -> str:
    if item.kind in {"message", "intermediate"}:
        return item.id
    if item.kind == "tool":
        return f"tool-{item.execution_id}"
    if item.kind == "artifact":
        return item.artifact.artifact_id
    return f"failure-{item.turn_id}"


def _sse(event: StreamEventPayload) -> str:
    return f"data: {event.model_dump_json()}\n\n"
