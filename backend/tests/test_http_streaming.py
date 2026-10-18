import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.http_streaming import _turn_events
from app.agents.models.http_streaming import (
    StreamClosing, StreamError, StreamEventPayload, StreamSnapshot, StreamTerminal, StreamUpsert,
)
from app.sessions.models.artifacts import ArtifactPayload
from app.sessions.models.conversation import ConversationReadActive, ConversationSnapshot
from app.sessions.models.turns import TerminalTurnKind, TurnSnapshot
from app.sessions.models.session import SessionReadExpired, SessionReadUnknown, SessionSnapshot
from app.sessions.models.timeline import TimelineMessage


type Update = ConversationReadActive[str, ArtifactPayload] | SessionReadExpired | SessionReadUnknown | None


def snapshot() -> ConversationSnapshot[str, ArtifactPayload]:
    return ConversationSnapshot(
        session=SessionSnapshot("session", datetime(2030, 1, 1, tzinfo=UTC), 1, "context", ()),
        artifacts=(), turns=(TurnSnapshot("turn", "request", "in_progress"),),
        timeline=(TimelineMessage("turn", "message", "assistant", "Hello"),),
        sequence=1,
    )


def collect(updates: tuple[Update, ...]) -> list[
    StreamEventPayload | None
]:
    async def source() -> AsyncIterator[Update]:
        for update in updates:
            yield update

    async def run() -> list[StreamEventPayload | None]:
        return [event async for event in _turn_events("turn", source())]

    return asyncio.run(run())


def test_stream_emits_changes_and_closing_before_terminal_after_turn_release() -> None:
    initial = snapshot()
    changed = replace(
        initial, timeline=(*initial.timeline, TimelineMessage("turn", "new", "assistant", "Done")),
        turns=(TurnSnapshot("turn", "request", "closing"),), sequence=2,
    )
    released = replace(changed, turns=(TurnSnapshot("turn", "request", "completed"),), sequence=3)
    events = collect(
        tuple(ConversationReadActive(value) for value in (initial, changed, changed, released)),
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
    initial = replace(snapshot(), turns=(TurnSnapshot("turn", "request", "closing"),))
    released = replace(initial, turns=(TurnSnapshot("turn", "request", "completed"),), sequence=2)
    events = collect(
        (ConversationReadActive(initial), ConversationReadActive(released)),
    )
    assert len(events) == 3
    assert isinstance(events[0], StreamSnapshot)
    assert events[0].snapshot.turns[0].status == "closing"
    assert events[1] is None
    assert isinstance(events[2], StreamTerminal)


@pytest.mark.parametrize("unavailable", ["limit", "unknown", "expired"])
def test_unavailable_observation_emits_error_and_stops(unavailable: str) -> None:
    update: Update = None
    if unavailable == "unknown":
        update = SessionReadUnknown("session")
    elif unavailable == "expired":
        update = SessionReadExpired("session", datetime.now(UTC) - timedelta(seconds=1))
    events = collect((update, ConversationReadActive(snapshot())))
    assert len(events) == 1
    error = events[0]
    assert isinstance(error, StreamError)
    assert error.reason == ("observation_limit" if unavailable == "limit" else "unavailable")


@pytest.mark.parametrize("outcome", ["completed", "generation_failed", "conflict"])
def test_terminal_snapshot_catch_up_uses_exact_retained_outcome(outcome: TerminalTurnKind) -> None:
    terminal = replace(snapshot(), turns=(TurnSnapshot("turn", "request", outcome),))
    events = collect((ConversationReadActive(terminal),))
    assert len(events) == 2
    assert isinstance(events[0], StreamSnapshot)
    assert isinstance(events[1], StreamTerminal)
    assert events[1].outcome == outcome


def test_final_output_upsert_precedes_terminal_from_same_snapshot() -> None:
    initial = snapshot()
    terminal = replace(
        initial,
        turns=(TurnSnapshot("turn", "request", "completed"),),
        timeline=(*initial.timeline, TimelineMessage("turn", "final", "assistant", "Final output")),
        sequence=3,
    )
    events = collect((ConversationReadActive(initial), ConversationReadActive(terminal)))
    assert [event.kind if event is not None else "heartbeat" for event in events] == [
        "snapshot", "heartbeat", "upsert", "terminal",
    ]
    upsert, completion = events[-2:]
    assert isinstance(upsert, StreamUpsert) and upsert.item == terminal.timeline[-1]
    assert isinstance(completion, StreamTerminal)
    assert upsert.sequence == completion.sequence == 3
