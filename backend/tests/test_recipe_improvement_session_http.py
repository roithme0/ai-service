from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.models.openai_agentic_generation import OpenAIAgenticGenerator
from app.recipe_improvement.http import get_recipe_improvement_session_store, get_agentic_generator
from app.recipe_improvement.http import _configured_agentic_generator
from app.recipe_improvement.session_lifecycle import RecipeImprovementSessionStore
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.sessions.text_sessions import MAX_MESSAGE_COUNT


RECIPE_VERSION_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class FakeGenerator:
    def __init__(self, text: str = "Test reply") -> None:
        self.text = text
        self.calls: list[AgenticGenerationRequest] = []
        self.fail = False
        self.before_return: Callable[[], None] | None = None
        self.responses: list[AgenticGenerationResponse] = []

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("model failure")
        if self.before_return is not None:
            self.before_return()
        if self.responses:
            return self.responses.pop(0)
        return AgenticGenerationResponse(output_items=(), tool_calls=(), text=self.text)


@pytest.fixture
def client() -> TestClient:
    store = RecipeImprovementSessionStore()
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fake_generator() -> Iterator[FakeGenerator]:
    generator = FakeGenerator()
    app.dependency_overrides[get_agentic_generator] = lambda: generator
    try:
        yield generator
    finally:
        app.dependency_overrides.pop(get_agentic_generator, None)


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
        "proposals": [],
        "terminal_turn_id": None,
        "terminal_turn_kind": None,
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


def test_oversized_initial_snapshot_context_is_rejected_at_creation(client: TestClient) -> None:
    request = valid_request()
    request["foodstuffs"] = [
        {"external_reference": index, "name": "N" * 50, "brand": "B" * 100, "unit": "G"}
        for index in range(1, 101)
    ]

    response = client.post("/api/v1/recipe-improvement/sessions", json=request)

    assert response.status_code == 422
    assert response.json()["kind"] == "invalid_input"
    assert response.json()["issues"] == [
        {"location": [], "message": "initial source recipe and foodstuffs context exceeds 16000 characters"}
    ]


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
    for index in range(MAX_MESSAGE_COUNT - 1):
        response = client.post(f"{session_url}/messages", json={"text": str(index)})
        assert response.status_code == 201

    rejected = client.post(f"{session_url}/messages", json={"text": "one too many"})
    read = client.get(session_url)

    assert rejected.status_code == 409
    assert read.status_code == 200
    assert len(read.json()["messages"]) == MAX_MESSAGE_COUNT - 1
    assert read.json()["messages"][-1] == {"role": "user", "text": "98"}


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


def test_turn_endpoint_returns_and_stores_assistant_reply(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "  question  "})

    response = client.post(f"{session_url}/turns")
    read = client.get(session_url)

    assert response.status_code == 201
    assert response.json()["message"] == {"role": "assistant", "text": "Test reply"}
    assert response.json()["proposals"] == []
    assert response.json()["turn_id"]
    generation_request = fake_generator.calls[0]
    assert generation_request.input_items[-1] == {"role": "user", "content": "  question  "}
    recipe_context = generation_request.input_items[0]["content"]
    assert isinstance(recipe_context, str)
    assert '"name":"Overnight oats"' in recipe_context
    assert '"name":"Oats"' in recipe_context
    assert "availability_reference_index" not in recipe_context
    assert generation_request.instructions == RECIPE_IMPROVEMENT_INSTRUCTIONS
    assert "stated goals, preferences, and constraints" in generation_request.instructions
    assert "For health-related questions" in generation_request.instructions
    assert "register_recipe_proposal" in generation_request.instructions
    assert read.json()["messages"] == [
        {"role": "user", "text": "  question  "},
        {"role": "assistant", "text": "Test reply"},
    ]


def test_turn_endpoint_is_unavailable_without_configured_generator(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RECIPE_IMPROVEMENT_OPENAI_MODEL", raising=False)
    _configured_agentic_generator.cache_clear()
    try:
        created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
        session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
        client.post(f"{session_url}/messages", json={"text": "question"})

        response = client.post(f"{session_url}/turns")

        assert response.status_code == 503
        assert response.json() == {"kind": "generator_unavailable"}
        assert len(client.get(session_url).json()["messages"]) == 1
    finally:
        _configured_agentic_generator.cache_clear()


def test_generator_requires_key_and_use_case_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _configured_agentic_generator.cache_clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RECIPE_IMPROVEMENT_OPENAI_MODEL", raising=False)
    try:
        assert get_agentic_generator() is None
        _configured_agentic_generator.cache_clear()
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        assert get_agentic_generator() is None
        _configured_agentic_generator.cache_clear()
        monkeypatch.setenv("RECIPE_IMPROVEMENT_OPENAI_MODEL", "gpt-5.6-sol")
        assert isinstance(get_agentic_generator(), OpenAIAgenticGenerator)
    finally:
        _configured_agentic_generator.cache_clear()


def test_turn_endpoint_reports_unknown_and_not_ready(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    unknown = client.post("/api/v1/recipe-improvement/sessions/missing/turns")
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    not_ready = client.post(f"{session_url}/turns")

    assert unknown.status_code == 404
    assert unknown.json() == {"kind": "unknown"}
    assert not_ready.status_code == 409
    assert not_ready.json() == {"kind": "not_ready"}
    assert fake_generator.calls == []


def test_turn_endpoint_reports_generation_failure_without_appending(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "question"})
    fake_generator.fail = True

    response = client.post(f"{session_url}/turns")

    assert response.status_code == 502
    assert response.json()["kind"] == "generation_failed"
    assert response.json()["turn_id"]
    assert client.get(session_url).json()["messages"] == [{"role": "user", "text": "question"}]


def test_turn_endpoint_rejects_reply_after_new_message(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "first"})

    def append_another_message() -> None:
        blocked = client.post(f"{session_url}/messages", json={"text": "second"})
        assert blocked.status_code == 409
        assert blocked.json() == {"kind": "busy"}

    fake_generator.before_return = append_another_message

    response = client.post(f"{session_url}/turns")

    assert response.status_code == 201
    assert client.get(session_url).json()["messages"] == [
        {"role": "user", "text": "first"},
        {"role": "assistant", "text": "Test reply"},
    ]


def test_turn_endpoint_reports_expiry_during_generation(fake_generator: FakeGenerator) -> None:
    clock = MutableClock(datetime(2026, 9, 13, 10, 30, tzinfo=UTC))
    store = RecipeImprovementSessionStore(clock=clock.now)
    app.dependency_overrides[get_recipe_improvement_session_store] = lambda: store
    try:
        client = TestClient(app)
        created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
        session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
        client.post(f"{session_url}/messages", json={"text": "question"})
        fake_generator.before_return = lambda: setattr(
            clock, "value", datetime.fromisoformat(created["expires_at"])
        )

        response = client.post(f"{session_url}/turns")

        assert response.status_code == 410
        assert response.json()["kind"] == "expired"
        assert client.get(session_url).status_code == 404
    finally:
        app.dependency_overrides.pop(get_recipe_improvement_session_store, None)


def test_turn_endpoint_uses_reserved_assistant_capacity(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    for index in range(MAX_MESSAGE_COUNT - 1):
        assert client.post(f"{session_url}/messages", json={"text": str(index)}).status_code == 201

    response = client.post(f"{session_url}/turns")
    answered = client.get(session_url)
    further_message = client.post(f"{session_url}/messages", json={"text": "one too many"})
    further_turn = client.post(f"{session_url}/turns")

    assert response.status_code == 201
    assert response.json()["message"] == {"role": "assistant", "text": "Test reply"}
    assert answered.status_code == 200
    assert len(answered.json()["messages"]) == MAX_MESSAGE_COUNT
    assert further_message.status_code == 409
    assert further_turn.status_code == 409
    assert len(fake_generator.calls) == 1


def test_partial_failure_returns_accepted_proposals_and_retry_is_stable(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).json()
    session_url = f"/api/v1/recipe-improvement/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "Propose one"})
    recipe = valid_request()["source"]["recipe"]
    recipe["ingredients"][0]["amount"] = "125.75"
    arguments = json.dumps({"base": {"kind": "source"}, "candidate": recipe})
    fake_generator.responses = [
        AgenticGenerationResponse(
            output_items=({"type": "function_call", "call_id": "call_1",
                           "name": "register_recipe_proposal", "arguments": arguments},),
            tool_calls=(AgenticToolCall("call_1", "register_recipe_proposal", arguments),),
            text=None,
        ),
        AgenticGenerationResponse((), (), None),
    ]
    first = client.post(f"{session_url}/turns")
    retry = client.post(f"{session_url}/turns")
    read = client.get(session_url)

    assert first.status_code == retry.status_code == 502
    assert first.json() == retry.json()
    assert first.json()["kind"] == "generation_failed"
    assert len(first.json()["proposals"]) == 1
    assert first.json()["proposals"][0]["turn_id"] == first.json()["turn_id"]
    assert len(fake_generator.calls) == 2
    assert read.json()["proposals"] == first.json()["proposals"]
    assert read.json()["terminal_turn_id"] == first.json()["turn_id"]
    assert read.json()["messages"] == [{"role": "user", "text": "Propose one"}]
