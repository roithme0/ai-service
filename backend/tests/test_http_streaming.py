import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.http_streaming import _turn_events
from app.agents.models.http_streaming import (
    StreamClosing, StreamError, StreamEventPayload, StreamSnapshot, StreamTerminal, StreamUpsert,
)
from app.sessions.models.artifacts import ArtifactPayload
from app.sessions.models.conversation import ConversationReadActive, ConversationSnapshot
from app.sessions.models.history import TerminalRecord
from app.sessions.models.session import SessionReadExpired, SessionReadUnknown, SessionSnapshot
from app.sessions.models.timeline import TimelineMessage


type Update = ConversationReadActive[str, ArtifactPayload] | SessionReadExpired | SessionReadUnknown | None


def snapshot() -> ConversationSnapshot[str, ArtifactPayload]:
    return ConversationSnapshot(
        session=SessionSnapshot("session", datetime(2030, 1, 1, tzinfo=UTC), 1, "context", ()),
        artifacts=(), terminal_turn_id=None, terminal_turn_kind=None,
        timeline=(TimelineMessage("turn", "message", "assistant", "Hello"),),
        active_turn_id="turn", active_turn_status="in_progress", sequence=1,
    )


def collect(updates: tuple[Update, ...], terminal_lookup: Callable[[], TerminalRecord | None]) -> list[
    StreamEventPayload | None
]:
    async def source() -> AsyncIterator[Update]:
        for update in updates:
            yield update

    async def run() -> list[StreamEventPayload | None]:
        return [event async for event in _turn_events("turn", source(), terminal_lookup)]

    return asyncio.run(run())


def test_stream_emits_changes_and_closing_before_terminal_after_turn_release() -> None:
    initial = snapshot()
    changed = replace(
        initial, timeline=(*initial.timeline, TimelineMessage("turn", "new", "assistant", "Done")),
        active_turn_status="closing", sequence=2,
    )
    released = replace(changed, active_turn_id=None, active_turn_status=None, sequence=3)
    events = collect(
        tuple(ConversationReadActive(value) for value in (initial, changed, changed, released)),
        lambda: TerminalRecord("turn", "completed"),
    )
    assert [event.kind if event is not None else "heartbeat" for event in events] == [
        "snapshot", "heartbeat", "upsert", "closing", "heartbeat", "heartbeat", "terminal",
    ]
    upsert = events[2]
    assert isinstance(upsert, StreamUpsert)
    assert upsert.identity == "new" and upsert.order == 1 and upsert.sequence == 2
    assert isinstance(events[3], StreamClosing)
    terminal = events[-1]
    assert isinstance(terminal, StreamTerminal)
    assert terminal.sequence == 3 and terminal.outcome == "completed"


def test_initial_closing_snapshot_does_not_repeat_items_or_closing_event() -> None:
    initial = replace(snapshot(), active_turn_status="closing")
    released = replace(initial, active_turn_id=None, active_turn_status=None, sequence=2)
    events = collect(
        (ConversationReadActive(initial), ConversationReadActive(released)),
        lambda: TerminalRecord("turn", "completed"),
    )
    assert len(events) == 3
    assert isinstance(events[0], StreamSnapshot)
    assert events[0].snapshot.active_turn_status == "closing"
    assert events[1] is None
    assert isinstance(events[2], StreamTerminal)


@pytest.mark.parametrize("unavailable", ["limit", "unknown", "expired"])
def test_unavailable_observation_emits_error_and_stops(unavailable: str) -> None:
    update: Update = None
    if unavailable == "unknown":
        update = SessionReadUnknown("session")
    elif unavailable == "expired":
        update = SessionReadExpired("session", datetime.now(UTC) - timedelta(seconds=1))
    events = collect((update, ConversationReadActive(snapshot())), lambda: None)
    assert len(events) == 1
    error = events[0]
    assert isinstance(error, StreamError)
    assert error.reason == ("observation_limit" if unavailable == "limit" else "unavailable")
