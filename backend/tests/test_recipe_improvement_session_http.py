from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.recipe_improvement.http import get_recipe_improvement_session_store
from app.recipe_improvement.session_lifecycle import RecipeImprovementSessionStore
from app.sessions.text_sessions import MAX_MESSAGE_COUNT


RECIPE_VERSION_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@pytest.fixture
def client() -> TestClient:
    store = RecipeImprovementSessionStore()
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def valid_request(foodstuff_reference: int = 1) -> dict[str, object]:
    return {
        "source": {
            "external_reference": RECIPE_VERSION_UUID,
            "recipe": {
                "name": "Overnight oats",
                "servings": 2,
                "preparation_time": 15,
                "origin_name": "Kitchen",
                "origin_url": "https://example.test/overnight-oats",
                "ingredients": [
                    {"index": 1, "amount": 125.75, "foodstuff_reference": foodstuff_reference}
                ],
                "steps": [{"index": 1, "description": "Combine and chill."}],
            },
        },
        "foodstuffs": [
            {"external_reference": 1, "name": "Oats", "brand": "Pantry", "unit": "G"}
        ],
    }


def test_create_and_read_return_accepted_snapshots_without_derived_index(client: TestClient) -> None:
    creation = client.post("/api/v1/recipe-improvement/sessions", json=valid_request())

    assert creation.status_code == 201
    created = creation.json()
    assert isinstance(created["session_id"], str)
    assert created["session_id"]
    assert datetime.fromisoformat(created["expires_at"]).tzinfo is not None

    read = client.get(f"/api/v1/recipe-improvement/sessions/{created['session_id']}")

    assert read.status_code == 200
    expected_source = valid_request()["source"]
    expected_source["recipe"]["ingredients"][0]["amount"] = "125.75"
    assert read.json() == {
        "session_id": created["session_id"],
        "expires_at": created["expires_at"],
        "source": expected_source,
        "foodstuffs": valid_request()["foodstuffs"],
        "messages": [],
    }
    assert "availability_reference_index" not in read.json()


def test_integer_amount_and_read_snapshot_can_initialize_sessions(client: TestClient) -> None:
    request = valid_request()
    request["source"]["recipe"]["ingredients"][0]["amount"] = 125

    initial_creation = client.post("/api/v1/recipe-improvement/sessions", json=request)

    assert initial_creation.status_code == 201
    snapshot = client.get(
        f"/api/v1/recipe-improvement/sessions/{initial_creation.json()['session_id']}"
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["source"]["recipe"]["ingredients"][0]["amount"] == "125"

    recreated = client.post(
        "/api/v1/recipe-improvement/sessions",
        json={"source": snapshot.json()["source"], "foodstuffs": snapshot.json()["foodstuffs"]},
    )

    assert recreated.status_code == 201


@pytest.mark.parametrize(
    ("payload", "location"),
    [
        ({**valid_request(), "source": {**valid_request()["source"], "external_reference": "bad"}}, ["source", "external_reference"]),
        ({**valid_request(), "foodstuffs": []}, ["source", "recipe", "ingredients", 0, "foodstuff_reference"]),
    ],
)
def test_invalid_input_returns_domain_issues_and_does_not_create_session(
    client: TestClient, payload: dict[str, object], location: list[str | int]
) -> None:
    response = client.post("/api/v1/recipe-improvement/sessions", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["kind"] == "invalid_input"
    assert body["issues"][0]["location"] == location
    assert client.get("/api/v1/recipe-improvement/sessions/not-created").status_code == 404


def test_unknown_session_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/recipe-improvement/sessions/missing")

    assert response.status_code == 404
    assert response.json() == {"kind": "unknown"}


def test_retained_expired_session_returns_gone_without_snapshot() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        client = TestClient(app)
        created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
        clock.value += timedelta(minutes=10)

        active_response = client.get(
            f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
        )

        assert active_response.status_code == 200
        assert active_response.json()["expires_at"] == created["expires_at"]
        clock.value += timedelta(minutes=80)

        response = client.get(f"/api/v1/recipe-improvement/sessions/{created['session_id']}")

        assert response.status_code == 410
        assert response.json() == {"kind": "expired"}
        assert "source" not in response.json()
        assert client.get(f"/api/v1/recipe-improvement/sessions/{created['session_id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_user_messages_append_in_order_and_preserve_submitted_text(client: TestClient) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"

    first = client.post(f"{session_url}/messages", json={"text": "  Make it lighter.  "})
    second = client.post(f"{session_url}/messages", json={"text": "Keep it filling."})
    read = client.get(session_url)

    assert first.status_code == 201
    assert first.json() == {"role": "user", "text": "  Make it lighter.  "}
    assert second.status_code == 201
    assert second.json() == {"role": "user", "text": "Keep it filling."}
    assert read.status_code == 200
    assert read.json()["messages"] == [
        {"role": "user", "text": "  Make it lighter.  "},
        {"role": "user", "text": "Keep it filling."},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "valid", "role": "assistant"},
        {"text": "valid", "unexpected": True},
        {"text": 123},
        {"text": ""},
        {"text": " \t "},
        {"text": "x" * 4_001},
    ],
)
def test_rejected_user_messages_do_not_change_the_conversation(
    client: TestClient, payload: dict[str, object]
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"

    response = client.post(f"{session_url}/messages", json=payload)
    read = client.get(session_url)

    assert response.status_code == 422
    assert read.status_code == 200
    assert read.json()["messages"] == []


def test_message_limit_returns_conflict_without_appending(client: TestClient) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    for index in range(MAX_MESSAGE_COUNT):
        response = client.post(f"{session_url}/messages", json={"text": str(index)})
        assert response.status_code == 201

    rejected = client.post(f"{session_url}/messages", json={"text": "one too many"})
    read = client.get(session_url)

    assert rejected.status_code == 409
    assert read.status_code == 200
    assert len(read.json()["messages"]) == MAX_MESSAGE_COUNT
    assert read.json()["messages"][-1] == {"role": "user", "text": "99"}


def test_unknown_and_expired_user_message_appends_do_not_expose_session_content() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        client = TestClient(app)
        unknown = client.post(
            "/api/v1/recipe-improvement/sessions/missing/messages", json={"text": "Hello"}
        )
        created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
        clock.value = datetime.fromisoformat(created["expires_at"])

        expired = client.post(
            f"/api/v1/recipe-improvement/sessions/{created['session_id']}/messages",
            json={"text": "Too late"},
        )
        read = client.get(f"/api/v1/recipe-improvement/sessions/{created['session_id']}")

        assert unknown.status_code == 404
        assert unknown.json() == {"kind": "unknown"}
        assert expired.status_code == 410
        assert expired.json() == {"kind": "expired"}
        assert "messages" not in expired.json()
        assert read.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_user_message_append_and_read_preserve_the_fixed_expiry() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        client = TestClient(app)
        created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
        clock.value += timedelta(minutes=10)

        appended = client.post(
            f"/api/v1/recipe-improvement/sessions/{created['session_id']}/messages",
            json={"text": "Still active"},
        )
        read = client.get(f"/api/v1/recipe-improvement/sessions/{created['session_id']}")

        assert appended.status_code == 201
        assert read.status_code == 200
        assert read.json()["expires_at"] == created["expires_at"]
    finally:
        app.dependency_overrides.clear()
