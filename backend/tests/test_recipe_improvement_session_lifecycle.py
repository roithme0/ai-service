from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.recipe_improvement.session_input import (
    RecipeImprovementSessionInput,
    RecipeImprovementSessionInputSuccess,
    validate_recipe_improvement_session_input,
)
from app.recipe_improvement.session_lifecycle import (
    SESSION_LIFETIME,
    RecipeImprovementSessionLookupExpired,
    RecipeImprovementSessionLookupSuccess,
    RecipeImprovementSessionLookupUnknown,
    RecipeImprovementSessionStore,
)
from app.sessions.text_sessions import TextSessionAppendAccepted


RECIPE_VERSION_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def valid_session_input() -> RecipeImprovementSessionInput:
    outcome = validate_recipe_improvement_session_input(
        {
            "external_reference": RECIPE_VERSION_UUID,
            "recipe": {
                "name": "Overnight oats",
                "servings": 2,
                "preparation_time": 15,
                "origin_name": "Kitchen",
                "origin_url": "https://example.test/overnight-oats",
                "ingredients": [{"index": 1, "amount": Decimal("125.75"), "foodstuff_reference": 1}],
                "steps": [{"index": 1, "description": "Combine and chill."}],
            },
        },
        [{"external_reference": 1, "name": "Oats", "brand": "Pantry", "unit": "G"}],
    )
    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)
    return outcome.session_input


def test_create_returns_unique_id_utc_expiry_and_retrievable_snapshot() -> None:
    created_at = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
    store = RecipeImprovementSessionStore(clock=lambda: created_at)

    first = store.create(valid_session_input())
    second = store.create(valid_session_input())
    outcome = store.lookup(first.session_id)

    assert first.session_id != second.session_id
    assert first.expires_at == created_at + SESSION_LIFETIME
    assert first.expires_at.tzinfo is UTC
    assert isinstance(outcome, RecipeImprovementSessionLookupSuccess)
    assert outcome.session.session_input == valid_session_input()


def test_lookup_does_not_extend_fixed_expiry() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    created = store.create(valid_session_input())

    clock.value += timedelta(minutes=89)
    outcome = store.lookup(created.session_id)

    assert isinstance(outcome, RecipeImprovementSessionLookupSuccess)
    assert outcome.session.expires_at == created.expires_at


def test_recipe_store_uses_shared_core_for_text_messages() -> None:
    store = RecipeImprovementSessionStore()
    created = store.create(valid_session_input())

    appended = store.append_user_message(created.session_id, "Can this be lighter?")
    outcome = store.lookup(created.session_id)

    assert isinstance(appended, TextSessionAppendAccepted)
    assert isinstance(outcome, RecipeImprovementSessionLookupSuccess)
    assert [(message.role, message.text) for message in outcome.session.messages] == [
        ("user", "Can this be lighter?")
    ]


@pytest.mark.parametrize("elapsed", [timedelta(), timedelta(seconds=1)])
def test_lookup_at_or_after_expiry_reports_expired_then_unknown(elapsed: timedelta) -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    created = store.create(valid_session_input())
    clock.value = created.expires_at + elapsed

    expired = store.lookup(created.session_id)
    later = store.lookup(created.session_id)

    assert isinstance(expired, RecipeImprovementSessionLookupExpired)
    assert expired.expires_at == created.expires_at
    assert isinstance(later, RecipeImprovementSessionLookupUnknown)


@pytest.mark.parametrize("session_id", ["", "missing"])
def test_unknown_ids_return_an_explicit_unknown_outcome(session_id: str) -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    created = store.create(valid_session_input())
    clock.value = created.expires_at + timedelta(seconds=1)

    outcome = store.lookup(session_id)

    assert isinstance(outcome, RecipeImprovementSessionLookupUnknown)
    assert outcome.session_id == session_id


def test_creation_opportunistically_discards_expired_sessions() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    expired_session = store.create(valid_session_input())
    clock.value = expired_session.expires_at
    store.create(valid_session_input())

    assert isinstance(store.lookup(expired_session.session_id), RecipeImprovementSessionLookupUnknown)


def test_session_snapshots_are_owned_and_immutable() -> None:
    store = RecipeImprovementSessionStore()
    input_snapshot = valid_session_input()
    created = store.create(input_snapshot)
    first_lookup = store.lookup(created.session_id)
    second_lookup = store.lookup(created.session_id)

    assert isinstance(first_lookup, RecipeImprovementSessionLookupSuccess)
    assert isinstance(second_lookup, RecipeImprovementSessionLookupSuccess)
    assert first_lookup.session is not second_lookup.session
    assert first_lookup.session.session_input is not input_snapshot
    assert first_lookup.session.session_input is not second_lookup.session.session_input
    assert first_lookup.session.session_input == input_snapshot
    assert first_lookup.session.messages == ()

