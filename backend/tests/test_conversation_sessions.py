from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.models.agentic_generation import AgenticToolCall
from app.sessions.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.tools import ToolExecution
from app.sessions.conversation import (
    ConversationMessageBusy,
    ConversationReadActive,
    ConversationSessionSettings,
    ConversationSessionStore,
    ConversationTurnReservation,
    TurnHistoryUnavailable,
)
from app.sessions.text_sessions import TextSessionAppendAccepted


@dataclass(frozen=True)
class Context:
    label: str


@dataclass(frozen=True)
class Artifact:
    message: str


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 25, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def store(clock: Clock) -> ConversationSessionStore[Context, Artifact]:
    return ConversationSessionStore(lifetime=timedelta(minutes=90), clock=clock.now)


def create(conversation: ConversationSessionStore[Context, Artifact], limit: int = 2) -> str:
    return conversation.create(Context("example"), ConversationSessionSettings(max_artifacts=limit)).session_id


def reserve(conversation: ConversationSessionStore[Context, Artifact], session_id: str) -> ConversationTurnReservation[Context, Artifact]:
    assert isinstance(conversation.append_user_message(session_id, "Continue"), TextSessionAppendAccepted)
    reserved = conversation.reserve_turn(session_id)
    assert isinstance(reserved, ConversationTurnReservation)
    return reserved


def test_stale_completion_does_not_end_newer_active_turn() -> None:
    conversation = store(Clock())
    session_id = create(conversation)
    first = reserve(conversation, session_id)
    assert conversation.fail_turn(session_id, first).kind == "generation_failed"
    second = reserve(conversation, session_id)
    assert conversation.complete_turn(session_id, first, "completed", "Stale").kind == "conflict"
    assert isinstance(conversation.append_user_message(session_id, "Busy"), ConversationMessageBusy)
    assert conversation.complete_turn(session_id, second, "completed", "Current").kind == "completed"


def test_concurrent_user_appends_are_recorded_once_with_derived_revision() -> None:
    conversation = store(Clock())
    session_id = create(conversation)

    def append(index: int) -> TextSessionAppendAccepted:
        result = conversation.append_user_message(session_id, str(index))
        assert isinstance(result, TextSessionAppendAccepted)
        return result

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = tuple(executor.map(append, range(30)))
    read = conversation.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.session.revision == len(results) == 30
    assert sorted(message.text for message in read.snapshot.session.messages) == sorted(str(index) for index in range(30))
    assert len(conversation.history(session_id)) == 30


def test_opportunistic_eviction_clears_stale_turn_bookkeeping() -> None:
    clock = Clock()
    conversation = store(clock)
    session_ids = tuple(create(conversation) for _ in range(4))
    turns = tuple(reserve(conversation, session_id) for session_id in session_ids)
    calls = tuple(conversation.record_call(session_id, turn.turn_id,
        AgenticToolCall("same", "present", "{}")) for session_id, turn in zip(session_ids, turns))
    for session_id, call in zip(session_ids, calls):
        conversation.start_execution(session_id, call)
    execution = ToolExecution(ArtifactToolOutput("presented"), ArtifactCandidate("example", Artifact("retained")))
    conversation.record_result(session_ids[0], calls[0], execution)
    clock.value += timedelta(minutes=90)
    assert conversation.read("unrelated").kind == "unknown"
    for session_id, turn, call in zip(session_ids, turns, calls):
        assert conversation.append_user_message(session_id, "late").kind == "unknown"
        assert conversation.reserve_turn(session_id).kind == "unknown"
        with pytest.raises(TurnHistoryUnavailable) as error:
            conversation.record_result(session_id, call, execution)
        assert error.value.kind == "unknown"
        assert conversation.fail_turn(session_id, turn).kind == "unknown"
        assert conversation.history(session_id) == ()
    assert conversation._sessions == conversation._history == conversation._artifacts == conversation._active_turns == {}
