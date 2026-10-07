from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from app.sessions.conversation import (
    ConversationReadActive, ConversationSessionSettings, ConversationSessionStore,
    ConversationTurnReservation,
)
from app.sessions.limits import MAX_MESSAGE_COUNT, MAX_MESSAGE_LENGTH
from app.sessions.models.session import (
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionAppendInvalidMessage,
    TextSessionAppendLimitReached,
    TextSessionReadExpired,
    TextSessionReadUnknown,
)


@dataclass
class MutableContext:
    values: list[str]


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def new_store(clock: MutableClock | None = None) -> ConversationSessionStore[MutableContext, str]:
    return ConversationSessionStore(timedelta(minutes=5), clock.now if clock else lambda: datetime.now(UTC))


def test_context_is_detached_from_caller_and_returned_snapshots() -> None:
    context = MutableContext(["original"])
    store = new_store()
    created = store.create(context, ConversationSessionSettings(2), owner="test:user")
    context.values.append("caller change")
    first = store.read(created.session_id)
    assert isinstance(first, ConversationReadActive)
    assert first.snapshot.session.payload.values == ["original"]
    first.snapshot.session.payload.values.append("returned change")
    second = store.read(created.session_id)
    assert isinstance(second, ConversationReadActive)
    assert second.snapshot.session.payload.values == ["original"]
    assert second.snapshot.session.messages == ()


def test_reads_and_messages_do_not_renew_consumer_supplied_lifetime() -> None:
    clock = MutableClock()
    store = new_store(clock)
    created = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user")
    clock.value += timedelta(minutes=4)
    assert isinstance(store.append_user_message(created.session_id, "  hello  "), TextSessionAppendAccepted)
    reservation = store.reserve_turn(created.session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    store.complete_turn(created.session_id, reservation, "completed", "answer")
    read = store.read(created.session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.session.expires_at == created.expires_at
    assert [(message.role, message.text) for message in read.snapshot.session.messages] == [
        ("user", "  hello  "), ("assistant", "answer"),
    ]
    clock.value = created.expires_at
    expired = store.read(created.session_id)
    assert isinstance(expired, TextSessionReadExpired)
    assert expired.expires_at == created.expires_at
    assert isinstance(store.read(created.session_id), TextSessionReadUnknown)


@pytest.mark.parametrize("text,reason", [(None, "blank_text"), (" \t ", "blank_text"),
                                        ("x" * (MAX_MESSAGE_LENGTH + 1), "text_too_long")])
def test_invalid_messages_do_not_append_history(text: object, reason: str) -> None:
    store = new_store()
    session_id = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user").session_id
    outcome = store.append_user_message(session_id, text)
    assert isinstance(outcome, TextSessionAppendInvalidMessage)
    assert outcome.reason == reason
    assert store.history(session_id) == ()
    assert store.read(session_id).snapshot.session.revision == 0


def test_concurrent_appends_reserve_final_answer_capacity_atomically() -> None:
    store = new_store()
    session_id = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user").session_id
    for index in range(MAX_MESSAGE_COUNT - 5):
        store.append_user_message(session_id, str(index))

    def append(index: int) -> bool:
        outcome = store.append_user_message(session_id, f"concurrent-{index}")
        assert isinstance(outcome, (TextSessionAppendAccepted, TextSessionAppendLimitReached))
        return isinstance(outcome, TextSessionAppendAccepted)

    with ThreadPoolExecutor(max_workers=8) as executor:
        accepted = tuple(executor.map(append, range(20)))
    assert sum(accepted) == 4
    assert len(store.history(session_id)) == MAX_MESSAGE_COUNT - 1
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    assert store.complete_turn(session_id, reservation, "completed", "answer").kind == "completed"
    assert store.read(session_id).snapshot.session.revision == MAX_MESSAGE_COUNT
    assert isinstance(store.append_user_message(session_id, "extra"), TextSessionAppendLimitReached)


def test_first_append_after_expiry_reports_expired_and_then_unknown() -> None:
    clock = MutableClock()
    store = new_store(clock)
    created = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user")
    clock.value = created.expires_at
    assert isinstance(store.append_user_message(created.session_id, "late"), TextSessionAppendExpired)
    assert isinstance(store.read(created.session_id), TextSessionReadUnknown)


def test_owner_metadata_follows_session_lifetime_and_lookup_does_not_consume_expiry() -> None:
    clock = MutableClock()
    store = new_store(clock)
    created = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user")
    assert store.belongs_to(created.session_id, "test:user")
    assert not store.belongs_to(created.session_id, "test:other")
    clock.value = created.expires_at
    assert not store.belongs_to(created.session_id, "test:other")
    assert isinstance(store.read(created.session_id), TextSessionReadExpired)
    assert not store.belongs_to(created.session_id, "test:user")
    replacement = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:other")
    assert store.belongs_to(replacement.session_id, "test:other")
    assert not store.belongs_to(replacement.session_id, "test:user")


def test_read_samples_time_after_waiting_for_the_store_lock() -> None:
    clock = MutableClock()
    store = new_store(clock)
    created = store.create(MutableContext([]), ConversationSessionSettings(2), owner="test:user")
    clock_read = Event()

    def signal_clock_read() -> datetime:
        clock_read.set()
        return clock.now()

    store._clock = signal_clock_read
    with ThreadPoolExecutor(max_workers=1) as executor:
        with store._lock:
            lookup = executor.submit(store.read, created.session_id)
            assert not clock_read.wait(timeout=0.1)
            clock.value = created.expires_at
        assert isinstance(lookup.result(), TextSessionReadExpired)


def test_concurrent_creation_uses_distinct_session_ids() -> None:
    store = new_store()

    def create(index: int) -> str:
        return store.create(MutableContext([str(index)]), ConversationSessionSettings(2), owner="test:user").session_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        sessions = tuple(executor.map(create, range(50)))
    assert len(set(sessions)) == 50
    assert all(isinstance(store.read(session_id), ConversationReadActive) for session_id in sessions)


@pytest.mark.parametrize("lifetime", [timedelta(), timedelta(seconds=-1)])
def test_nonpositive_session_lifetime_is_rejected(lifetime: timedelta) -> None:
    with pytest.raises(ValueError, match="lifetime must be positive"):
        ConversationSessionStore[str, str](lifetime)


def test_naive_clock_is_rejected() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=5), lambda: datetime(2026, 10, 3))
    with pytest.raises(ValueError, match="timezone-aware"):
        store.create("context", ConversationSessionSettings(2), owner="test:user")
