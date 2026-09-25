from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.sessions.conversation import (
    ConversationMessageBusy,
    ConversationReadActive,
    ConversationSessionSettings,
    ConversationSessionStore,
    ConversationStageAccepted,
    ConversationStageRejected,
    ConversationTurnReservation,
    ConversationTurnView,
)
from app.sessions.text_sessions import TextSessionAppendAccepted, TextSessionReadUnknown


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


def test_staged_artifact_is_turn_visible_then_published_with_shared_identity() -> None:
    clock = Clock()
    conversation = store(clock)
    session_id = create(conversation)
    reserved = reserve(conversation, session_id)

    staged = conversation.stage_artifact(session_id, reserved.turn_id, "example", Artifact("Hello"))
    assert isinstance(staged, ConversationStageAccepted)
    assert staged.artifact.created_at == clock.value
    assert staged.artifact.type == "example"
    assert staged.artifact.order == 1
    assert staged.artifact.turn_id == reserved.turn_id
    view = conversation.inspect_turn(session_id, reserved.turn_id)
    assert isinstance(view, ConversationTurnView)
    assert view.snapshot.payload == Context("example")
    assert view.artifacts == (staged.artifact,)
    pending = conversation.read(session_id)
    assert isinstance(pending, ConversationReadActive)
    assert pending.snapshot.artifacts == ()
    assert isinstance(conversation.append_user_message(session_id, "Busy"), ConversationMessageBusy)
    assert conversation.reserve_turn(session_id).kind == "busy"

    completed = conversation.complete_turn(session_id, reserved, "completed", "Done")
    assert completed.kind == "completed"
    assert completed.artifacts == (staged.artifact,)
    published = conversation.read(session_id)
    assert isinstance(published, ConversationReadActive)
    assert published.snapshot.artifacts == completed.artifacts
    assert published.snapshot.terminal_turn_id == reserved.turn_id
    assert published.snapshot.session.messages[-1].turn_id == reserved.turn_id


@pytest.mark.parametrize("limit", [1, 3])
def test_limit_counts_staged_artifacts_and_failure_releases_capacity(limit: int) -> None:
    conversation = store(Clock())
    session_id = create(conversation, limit)
    reserved = reserve(conversation, session_id)
    for _ in range(limit):
        assert isinstance(conversation.stage_artifact(session_id, reserved.turn_id, "example", Artifact("pending")), ConversationStageAccepted)
    assert conversation.stage_artifact(session_id, reserved.turn_id, "example", Artifact("extra")) == ConversationStageRejected("limit_reached")
    failed = conversation.fail_turn(session_id, reserved)
    assert failed.kind == "generation_failed"
    assert failed.artifacts == ()
    read = conversation.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    assert conversation.reserve_turn(session_id) == failed
    next_turn = reserve(conversation, session_id)
    assert isinstance(conversation.stage_artifact(session_id, next_turn.turn_id, "example", Artifact("replacement")), ConversationStageAccepted)


def test_different_sessions_in_one_store_use_their_own_artifact_limits() -> None:
    conversation = store(Clock())
    small = create(conversation, limit=1)
    large = create(conversation, limit=2)
    small_turn = reserve(conversation, small)
    large_turn = reserve(conversation, large)

    assert isinstance(conversation.stage_artifact(small, small_turn.turn_id, "example", Artifact("one")), ConversationStageAccepted)
    assert conversation.stage_artifact(small, small_turn.turn_id, "example", Artifact("two")).kind == "limit_reached"
    assert isinstance(conversation.stage_artifact(large, large_turn.turn_id, "example", Artifact("one")), ConversationStageAccepted)
    assert isinstance(conversation.stage_artifact(large, large_turn.turn_id, "example", Artifact("two")), ConversationStageAccepted)
    assert conversation.stage_artifact(large, large_turn.turn_id, "example", Artifact("three")).kind == "limit_reached"


def test_failure_discards_only_current_artifacts_and_preserves_prior_artifacts() -> None:
    conversation = store(Clock())
    session_id = create(conversation)
    first = reserve(conversation, session_id)
    prior = conversation.stage_artifact(session_id, first.turn_id, "example", Artifact("prior"))
    assert isinstance(prior, ConversationStageAccepted)
    assert conversation.complete_turn(session_id, first, "completed", "Done").kind == "completed"
    second = reserve(conversation, session_id)
    pending = conversation.stage_artifact(session_id, second.turn_id, "example", Artifact("pending"), prior.artifact.artifact_id)
    assert isinstance(pending, ConversationStageAccepted)
    assert conversation.stage_artifact(session_id, second.turn_id, "example", Artifact("extra")).kind == "limit_reached"
    assert conversation.fail_turn(session_id, second).kind == "generation_failed"
    read = conversation.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == (prior.artifact,)
    assert conversation.append_user_message(session_id, "Again").kind == "accepted"
    next_turn = conversation.reserve_turn(session_id)
    assert isinstance(next_turn, ConversationTurnReservation)
    assert next_turn.previous_artifacts == (prior.artifact,)
    assert conversation.stage_artifact(session_id, next_turn.turn_id, "example", Artifact("new"), "missing").kind == "missing_reference"
    replacement = conversation.stage_artifact(session_id, next_turn.turn_id, "example", Artifact("new"), prior.artifact.artifact_id)
    assert isinstance(replacement, ConversationStageAccepted)
    assert replacement.artifact.order == 2


def test_expiry_clears_pending_artifacts_and_rejects_stale_reservations() -> None:
    clock = Clock()
    conversation = store(clock)
    session_id = create(conversation)
    reserved = reserve(conversation, session_id)
    assert isinstance(conversation.stage_artifact(session_id, reserved.turn_id, "example", Artifact("pending")), ConversationStageAccepted)
    clock.value = reserved.snapshot.expires_at
    assert conversation.stage_artifact(session_id, reserved.turn_id, "example", Artifact("late")).kind == "expired"
    assert isinstance(conversation.read(session_id), TextSessionReadUnknown)
    assert conversation.complete_turn(session_id, reserved, "completed", "Late").kind == "unknown"


def test_opportunistic_eviction_clears_stale_turn_bookkeeping() -> None:
    clock = Clock()
    conversation = store(clock)
    append_id = create(conversation)
    reserve_id = create(conversation)
    stage_id = create(conversation)
    fail_id = create(conversation)
    append_turn = reserve(conversation, append_id)
    reserve(conversation, reserve_id)
    stage_turn = reserve(conversation, stage_id)
    fail_turn = reserve(conversation, fail_id)
    assert isinstance(conversation.stage_artifact(append_id, append_turn.turn_id, "example", Artifact("pending")), ConversationStageAccepted)

    clock.value = append_turn.snapshot.expires_at
    assert isinstance(conversation.read("unrelated"), TextSessionReadUnknown)
    assert conversation.append_user_message(append_id, "Late").kind == "unknown"
    assert conversation.reserve_turn(reserve_id).kind == "unknown"
    assert conversation.stage_artifact(stage_id, stage_turn.turn_id, "example", Artifact("Late")).kind == "unknown"
    assert conversation.fail_turn(fail_id, fail_turn).kind == "unknown"
    assert isinstance(conversation.read(append_id), TextSessionReadUnknown)


def test_stale_completion_does_not_end_newer_active_turn() -> None:
    conversation = store(Clock())
    session_id = create(conversation)
    first = reserve(conversation, session_id)
    assert conversation.fail_turn(session_id, first).kind == "generation_failed"
    second = reserve(conversation, session_id)
    assert conversation.complete_turn(session_id, first, "completed", "Stale").kind == "conflict"
    assert isinstance(conversation.append_user_message(session_id, "Busy"), ConversationMessageBusy)
    assert conversation.complete_turn(session_id, second, "completed", "Current").kind == "completed"
