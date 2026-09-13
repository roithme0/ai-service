from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest

from app.sessions.text_sessions import (
    MAX_MESSAGE_COUNT,
    MAX_MESSAGE_LENGTH,
    EphemeralTextSessionStore,
    TextSessionAppendAccepted,
    TextSessionAppendConflict,
    TextSessionAppendExpired,
    TextSessionAppendInvalidMessage,
    TextSessionAppendLimitReached,
    TextSessionAppendUnknown,
    TextSessionReadActive,
    TextSessionReadExpired,
    TextSessionReadUnknown,
)


@dataclass
class MutablePayload:
    values: list[str]


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def new_store(clock: MutableClock | None = None) -> EphemeralTextSessionStore[MutablePayload]:
    return EphemeralTextSessionStore(
        lifetime=timedelta(minutes=5),
        clock=clock.now if clock is not None else lambda: datetime.now(UTC),
    )


def test_core_is_payload_agnostic_and_owns_payload_and_returned_data() -> None:
    payload = MutablePayload(values=["original"])
    store = new_store()
    created = store.create(payload)
    payload.values.append("caller change")

    first = store.read(created.session_id)
    assert isinstance(first, TextSessionReadActive)
    assert first.session.payload.values == ["original"]
    first.session.payload.values.append("returned change")
    second = store.read(created.session_id)

    assert isinstance(second, TextSessionReadActive)
    assert second.session.payload.values == ["original"]
    assert second.session.messages == ()


def test_lifetime_is_consumer_supplied_and_reads_and_appends_do_not_renew_it() -> None:
    created_at = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
    clock = MutableClock(created_at)
    store = new_store(clock)
    created = store.create(MutablePayload(values=[]))
    clock.value += timedelta(minutes=4)

    assert isinstance(store.read(created.session_id), TextSessionReadActive)
    assert isinstance(store.append(created.session_id, "user", "hello"), TextSessionAppendAccepted)
    active = store.read(created.session_id)

    assert isinstance(active, TextSessionReadActive)
    assert active.session.expires_at == created_at + timedelta(minutes=5)


def test_messages_preserve_text_and_append_order() -> None:
    store = new_store()
    created = store.create(MutablePayload(values=[]))

    assert isinstance(store.append(created.session_id, "user", "  question  "), TextSessionAppendAccepted)
    assert isinstance(store.append(created.session_id, "assistant", "answer"), TextSessionAppendAccepted)
    outcome = store.read(created.session_id)

    assert isinstance(outcome, TextSessionReadActive)
    assert [(message.role, message.text) for message in outcome.session.messages] == [
        ("user", "  question  "),
        ("assistant", "answer"),
    ]


@pytest.mark.parametrize(
    ("role", "text", "reason"),
    [
        ("system", "message", "unsupported_role"),
        ("user", " \t ", "blank_text"),
        ("user", "x" * (MAX_MESSAGE_LENGTH + 1), "text_too_long"),
    ],
)
def test_invalid_messages_leave_the_conversation_unchanged(
    role: object, text: object, reason: str
) -> None:
    store = new_store()
    created = store.create(MutablePayload(values=[]))

    outcome = store.append(created.session_id, role, text)
    later = store.read(created.session_id)

    assert isinstance(outcome, TextSessionAppendInvalidMessage)
    assert outcome.reason == reason
    assert isinstance(later, TextSessionReadActive)
    assert later.session.messages == ()


def test_message_limit_rejects_an_extra_append_without_storing_it() -> None:
    store = new_store()
    created = store.create(MutablePayload(values=[]))
    for index in range(MAX_MESSAGE_COUNT):
        assert isinstance(store.append(created.session_id, "user", str(index)), TextSessionAppendAccepted)

    outcome = store.append(created.session_id, "assistant", "one too many")
    later = store.read(created.session_id)

    assert isinstance(outcome, TextSessionAppendLimitReached)
    assert isinstance(later, TextSessionReadActive)
    assert len(later.session.messages) == MAX_MESSAGE_COUNT


def test_capped_appends_reserve_capacity_atomically() -> None:
    store = new_store()
    created = store.create(MutablePayload(values=[]))

    def append(index: int) -> object:
        return store.append_with_max_message_count(created.session_id, "user", str(index), 3)

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(append, range(20)))
    later = store.read(created.session_id)

    assert sum(isinstance(outcome, TextSessionAppendAccepted) for outcome in outcomes) == 3
    assert sum(isinstance(outcome, TextSessionAppendLimitReached) for outcome in outcomes) == 17
    assert isinstance(later, TextSessionReadActive)
    assert len(later.session.messages) == 3


def test_expired_and_unknown_results_are_distinct_for_read_and_append() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_store(clock)
    created = store.create(MutablePayload(values=[]))
    clock.value = created.expires_at

    expired_append = store.append(created.session_id, "user", "late")
    later_read = store.read(created.session_id)
    unknown_append = store.append("missing", "user", "missing")

    assert isinstance(expired_append, TextSessionAppendExpired)
    assert isinstance(later_read, TextSessionReadUnknown)
    assert isinstance(unknown_append, TextSessionAppendUnknown)


def test_first_read_of_held_expired_session_reports_expired() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_store(clock)
    created = store.create(MutablePayload(values=[]))
    clock.value = created.expires_at

    outcome = store.read(created.session_id)

    assert isinstance(outcome, TextSessionReadExpired)
    assert outcome.expires_at == created.expires_at


def test_read_samples_time_after_waiting_for_the_store_lock() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_store(clock)
    created = store.create(MutablePayload(values=[]))
    clock_read = Event()

    def signal_clock_read() -> datetime:
        clock_read.set()
        return clock.now()

    store._clock = signal_clock_read
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with store._lock:
            lookup = executor.submit(store.read, created.session_id)
            assert not clock_read.wait(timeout=0.1)
            clock.value = created.expires_at
        outcome = lookup.result()
    finally:
        executor.shutdown()

    assert isinstance(outcome, TextSessionReadExpired)


def test_concurrent_appends_keep_every_message_in_one_order() -> None:
    store = new_store()
    created = store.create(MutablePayload(values=[]))
    submitted = [f"message-{index}" for index in range(50)]
    start = Lock()

    def append(text: str) -> object:
        with start:
            return store.append(created.session_id, "user", text)

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(append, submitted))
    later = store.read(created.session_id)

    assert all(isinstance(outcome, TextSessionAppendAccepted) for outcome in outcomes)
    assert isinstance(later, TextSessionReadActive)
    assert len(later.session.messages) == len(submitted)
    assert {message.text for message in later.session.messages} == set(submitted)


def test_concurrent_creation_does_not_reuse_active_ids() -> None:
    generated_ids = iter(f"session-{index}" for index in range(100))
    generator_lock = Lock()

    def next_id() -> str:
        with generator_lock:
            return next(generated_ids)

    store = EphemeralTextSessionStore[MutablePayload](
        lifetime=timedelta(minutes=5), session_id_generator=next_id
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        created = list(executor.map(lambda _: store.create(MutablePayload(values=[])), range(50)))

    assert len({session.session_id for session in created}) == 50
    assert all(isinstance(store.read(session.session_id), TextSessionReadActive) for session in created)


def test_conditional_append_checks_only_its_own_session_revision() -> None:
    store = EphemeralTextSessionStore[str](lifetime=timedelta(minutes=5))
    first_id = store.create("first").session_id
    second_id = store.create("second").session_id
    first = store.read(first_id)
    assert isinstance(first, TextSessionReadActive)
    assert first.session.revision == 0
    assert isinstance(store.append(second_id, "user", "other session"), TextSessionAppendAccepted)
    accepted = store.append_if_revision(first_id, first.session.revision, "user", "first message")
    assert isinstance(accepted, TextSessionAppendAccepted)
    later = store.read(first_id)
    assert isinstance(later, TextSessionReadActive)
    assert later.session.revision == 1

    assert isinstance(
        store.append_if_revision(first_id, first.session.revision, "assistant", "stale"),
        TextSessionAppendConflict,
    )
    after_conflict = store.read(first_id)
    assert isinstance(after_conflict, TextSessionReadActive)
    assert [message.text for message in after_conflict.session.messages] == ["first message"]
