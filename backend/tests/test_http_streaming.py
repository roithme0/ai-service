import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.http_streaming import _turn_events
from app.agents.models.http_streaming import (
    StreamClosing, StreamError, StreamEventPayload, StreamSnapshot, StreamTerminal, StreamUpsert,
)
from app.sessions.models.artifacts import ArtifactPayload, PublishedArtifact
from app.sessions.models.conversation import ConversationReadActive, ConversationSnapshot
from app.sessions.models.turns import TerminalTurnKind, TurnSnapshot
from app.sessions.models.session import SessionReadExpired, SessionReadUnknown, SessionSnapshot
from app.sessions.models.timeline import TimelineArtifact, TimelineMessage


type Update = ConversationReadActive[str, ArtifactPayload] | SessionReadExpired | SessionReadUnknown | None


def snapshot() -> ConversationSnapshot[str, ArtifactPayload]:
    return ConversationSnapshot(
        session=SessionSnapshot("session", datetime(2030, 1, 1, tzinfo=UTC), 1, "context", ()),
        turns=(TurnSnapshot("turn", "request", "in_progress", (
            TimelineMessage("turn", "request", "user", "Request"),
            TimelineMessage("turn", "message", "assistant", "Hello"),
        )),),
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
        initial, turns=(replace(initial.turns[0], status="closing", timeline=(
            *initial.turns[0].timeline, TimelineMessage("turn", "new", "assistant", "Done"),
        )),), sequence=2,
    )
    released = replace(changed, turns=(replace(changed.turns[0], status="completed"),), sequence=3)
    events = collect(
        tuple(ConversationReadActive(value) for value in (initial, changed, changed, released)),
    )
    assert [event.kind if event is not None else "heartbeat" for event in events] == [
        "snapshot", "heartbeat", "upsert", "closing", "heartbeat", "heartbeat", "terminal",
    ]
    upsert = events[2]
    assert isinstance(upsert, StreamUpsert)
    assert upsert.identity == "new" and upsert.order == 2 and upsert.sequence == 2
    assert isinstance(events[3], StreamClosing)
    terminal = events[-1]
    assert isinstance(terminal, StreamTerminal)
    assert terminal.sequence == 3 and terminal.outcome == "completed"


def test_initial_closing_snapshot_does_not_repeat_items_or_closing_event() -> None:
    initial = replace(snapshot(), turns=(replace(snapshot().turns[0], status="closing"),))
    released = replace(initial, turns=(replace(initial.turns[0], status="completed"),), sequence=2)
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
    terminal = replace(snapshot(), turns=(replace(snapshot().turns[0], status=outcome),))
    events = collect((ConversationReadActive(terminal),))
    assert len(events) == 2
    assert isinstance(events[0], StreamSnapshot)
    assert isinstance(events[1], StreamTerminal)
    assert events[1].outcome == outcome


def test_final_output_upsert_precedes_terminal_from_same_snapshot() -> None:
    initial = snapshot()
    terminal = replace(
        initial,
        turns=(replace(initial.turns[0], status="completed", timeline=(
            *initial.turns[0].timeline, TimelineMessage("turn", "final", "assistant", "Final output"),
        )),),
        sequence=3,
    )
    events = collect((ConversationReadActive(initial), ConversationReadActive(terminal)))
    assert [event.kind if event is not None else "heartbeat" for event in events] == [
        "snapshot", "heartbeat", "upsert", "terminal",
    ]
    upsert, completion = events[-2:]
    assert isinstance(upsert, StreamUpsert) and upsert.item == terminal.turns[0].timeline[-1]
    assert isinstance(completion, StreamTerminal)
    assert upsert.sequence == completion.sequence == 3


def test_upserts_are_turn_local_and_embed_artifacts_without_a_second_payload() -> None:
    initial = snapshot()
    history = TurnSnapshot[ArtifactPayload]("old", "old-request", "completed", (
        TimelineMessage("old", "old-request", "user", "Earlier"),
        TimelineMessage("old", "old-answer", "assistant", "Earlier answer"),
    ))
    initial = replace(initial, turns=(history, initial.turns[0]))
    artifact = PublishedArtifact(
        artifact_id="artifact", type="json", created_at=datetime(2030, 1, 1, tzinfo=UTC),
        turn_id="turn", payload=ArtifactPayload(title="Data", payload={"value": 42}), order=17,
    )
    completed = replace(initial, sequence=3, turns=(history, replace(
        initial.turns[1], status="completed", timeline=(
            *initial.turns[1].timeline, TimelineArtifact("turn", artifact),
            TimelineMessage("turn", "final", "assistant", "Final"),
        ),
    )))
    events = collect((ConversationReadActive(initial), ConversationReadActive(completed)))
    upserts = [event for event in events if isinstance(event, StreamUpsert)]
    assert [(event.identity, event.order) for event in upserts] == [("artifact", 2), ("final", 3)]
    assert upserts[0].model_dump(mode="json")["item"]["artifact"]["payload"]["payload"] == {"value": 42}
    encoded_artifact = upserts[0].model_dump(mode="json")["item"]["artifact"]
    assert encoded_artifact["created_at"] == "2030-01-01T00:00:00+00:00"
    catch_up = collect((ConversationReadActive(completed),))[0]
    assert isinstance(catch_up, StreamSnapshot)
    assert catch_up.snapshot.model_dump(mode="json")["turns"][1]["timeline"][2]["artifact"] == encoded_artifact
    assert "artifact" not in upserts[0].model_dump()
    initial_event = events[0]
    assert isinstance(initial_event, StreamSnapshot)
    assert set(initial_event.snapshot.model_dump()) == {"session_id", "expires_at", "turns", "sequence"}
    assert initial_event.snapshot.turns[0].timeline[0].turn_id == "old"
    assert isinstance(events[-1], StreamTerminal)
