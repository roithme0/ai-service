from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from turn_observation import observe_turn

from app.sessions.model_sessions import ModelAgent, create_model_agent
from app.agents.wiring import configure_agents
from app.core.config import Settings
from app.main import app
from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.http import AgentTransport, ConversationTransport, _demo_issue, _context_issue, get_agent_registry
from app.demo.agent import create_demo_agent
from app.sessions.model_sessions import new_model_session_store
from app.sessions.instructions import CONVERSATION_INSTRUCTIONS
from app.agents.context import MAX_CONTEXT_LENGTH
from app.sessions.limits import MAX_MESSAGE_COUNT, MAX_MESSAGE_LENGTH


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
        return AgenticGenerationResponse(output_items=({"type": "message", "role": "assistant", "phase": "final_answer", "content": self.text},), tool_calls=(), text=self.text)


@pytest.fixture
def client(fake_generator: FakeGenerator) -> Iterator[TestClient]:
    store = new_model_session_store()
    agent = create_model_agent(fake_generator, store)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(agent)
    try:
        with TestClient(app, headers={"X-Application-User": "test:user"}) as running:
            yield running
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fake_generator() -> FakeGenerator:
    return FakeGenerator()


def kochwiki_registry(agent: ModelAgent | None) -> dict[str, ConversationTransport | None]:
    return {"kochwiki": AgentTransport(agent, lambda value: value, _context_issue) if agent else None,
            "demo": AgentTransport(create_demo_agent(delay_seconds=0), lambda value: value,
                                   _demo_issue)}


def valid_request(foodstuff_reference: int = 1) -> dict[str, object]:
    return {"context": {
        "source": {
            "external_reference": RECIPE_VERSION_UUID,
            "recipe": {
                "name": "Overnight oats",
                "servings": 2,
                "preparation_time": 15,
                "ingredients": [
                    {"index": 1, "amount": 125.75, "foodstuff_reference": foodstuff_reference}
                ],
                "steps": [{"index": 1, "description": "Combine and chill."}],
            },
        },
        "foodstuffs": [
            {"external_reference": 1, "name": "Oats", "brand": "Pantry", "unit": "G",
             "unit_verbose": "g", "kcal": 370, "carbs": 60, "protein": 13, "fat": 7}
        ],
    }}


def test_create_and_read_return_accepted_snapshots_without_derived_index(client: TestClient) -> None:
    creation = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()})

    assert creation.status_code == 201
    created = creation.json()
    assert isinstance(created["session_id"], str)
    assert created["session_id"]
    assert datetime.fromisoformat(created["expires_at"]).tzinfo is not None

    read = client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}")

    assert read.status_code == 200
    assert read.json() == {
        "session_id": created["session_id"],
        "expires_at": created["expires_at"],
        "messages": [],
        "artifacts": [],
        "terminal_turn_id": None,
        "terminal_turn_kind": None,
        "timeline": [],
        "active_turn_id": None,
        "active_turn_status": None,
        "sequence": 0,
    }
    assert "availability_reference_index" not in read.json()


def test_integer_amount_is_accepted_without_exposing_input(client: TestClient) -> None:
    request = valid_request()
    request["context"]["source"]["recipe"]["ingredients"][0]["amount"] = 125

    initial_creation = client.post("/api/v1/agents/kochwiki/sessions", json={"input": request})

    assert initial_creation.status_code == 201
    snapshot = client.get(
        f"/api/v1/agents/kochwiki/sessions/{initial_creation.json()['session_id']}"
    )
    assert snapshot.status_code == 200
    assert "source" not in snapshot.json()
    assert "foodstuffs" not in snapshot.json()


def test_oversized_initial_snapshot_context_is_rejected_at_creation(client: TestClient) -> None:
    request = valid_request()
    request["context"] = {"description": "x" * MAX_CONTEXT_LENGTH}

    response = client.post("/api/v1/agents/kochwiki/sessions", json={"input": request})

    assert response.status_code == 422
    assert response.json()["kind"] == "invalid_input"
    assert response.json()["detail"] == [
        {"loc": ["body", "input", "context"], "msg": f"initial context exceeds {MAX_CONTEXT_LENGTH} characters",
         "type": "value_error"}
    ]


@pytest.mark.parametrize(
    ("payload", "location"),
    [(None, []), ({}, ["context"]), ({"context": []}, ["context"]),
     ({"context": {}, "tools": []}, ["tools"])],
)
def test_invalid_context_returns_details_without_creating_session(
    client: TestClient, payload: object, location: list[str | int]
) -> None:
    response = client.post("/api/v1/agents/kochwiki/sessions", json={"input": payload})
    assert response.status_code == 422
    assert response.json()["kind"] == "invalid_input"
    assert response.json()["detail"][0]["loc"] == ["body", "input", *location]
    assert client.get("/api/v1/agents/kochwiki/sessions/not-created").status_code == 404


def test_unknown_session_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/agents/kochwiki/sessions/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found", "kind": "unknown"}


def test_arbitrary_domain_context_is_retained_for_every_turn(
    client: TestClient, fake_generator: FakeGenerator,
) -> None:
    context = {"device": {"id": "lamp", "enabled": False}, "metadata": [None, 1.25, "1.250"]}
    creation = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {"context": context}})
    assert creation.status_code == 201
    session_url = f"/api/v1/agents/kochwiki/sessions/{creation.json()['session_id']}"
    for text in ("first", "second"):
        assert client.post(f"{session_url}/messages", json={"text": text}).status_code == 201
        assert observe_turn(client, f"{session_url}/turns").status_code == 200
    first_context = str(fake_generator.calls[0].input_items[0]["content"])
    assert json.loads(first_context.split("\n", 1)[1]) == context
    assert fake_generator.calls[1].input_items[0]["content"] == first_context
    assert "context" not in client.get(session_url).json()


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_http_rejects_non_finite_context_numbers(client: TestClient, number: str) -> None:
    response = client.post(
        "/api/v1/agents/kochwiki/sessions",
        content='{"input":{"context":{"number":' + number + '}}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["kind"] == "invalid_input"


def test_retained_expired_session_returns_gone_without_snapshot() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_model_session_store(clock=clock.now)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(create_model_agent(FakeGenerator(), store))
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
        clock.value += timedelta(minutes=10)

        active_response = client.get(
            f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
        )

        assert active_response.status_code == 200
        assert active_response.json()["expires_at"] == created["expires_at"]
        clock.value += timedelta(minutes=80)

        denied = client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}",
                            headers={"X-Application-User": "test:other"})
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Session not found", "kind": "unknown"}

        response = client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}")

        assert response.status_code == 410
        assert response.json() == {"detail": "Session expired", "kind": "expired"}
        assert "source" not in response.json()
        assert client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_user_messages_append_in_order_and_preserve_submitted_text(client: TestClient) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"

    first = client.post(f"{session_url}/messages", json={"text": "  Make it lighter.  "})
    second = client.post(f"{session_url}/messages", json={"text": "Keep it filling."})
    read = client.get(session_url)

    assert first.status_code == 201
    assert first.json() == {"role": "user", "text": "  Make it lighter.  ", "turn_id": None}
    assert second.status_code == 201
    assert second.json() == {"role": "user", "text": "Keep it filling.", "turn_id": None}
    assert read.status_code == 200
    assert read.json()["messages"] == [
        {"role": "user", "text": "  Make it lighter.  ", "turn_id": None},
        {"role": "user", "text": "Keep it filling.", "turn_id": None},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "valid", "role": "assistant"},
        {"text": "valid", "unexpected": True},
        {"text": 123},
        {"text": ""},
        {"text": " \t "},
        {"text": "x" * (MAX_MESSAGE_LENGTH + 1)},
    ],
)
def test_rejected_user_messages_do_not_change_the_conversation(
    client: TestClient, payload: dict[str, object]
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"

    response = client.post(f"{session_url}/messages", json=payload)
    read = client.get(session_url)

    assert response.status_code == 422
    assert read.status_code == 200
    assert read.json()["messages"] == []


def test_message_limit_returns_conflict_without_appending(client: TestClient) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    for index in range(MAX_MESSAGE_COUNT - 1):
        response = client.post(f"{session_url}/messages", json={"text": str(index)})
        assert response.status_code == 201

    rejected = client.post(f"{session_url}/messages", json={"text": "one too many"})
    read = client.get(session_url)

    assert rejected.status_code == 409
    assert read.status_code == 200
    assert len(read.json()["messages"]) == MAX_MESSAGE_COUNT - 1
    assert read.json()["messages"][-1] == {
        "role": "user", "text": str(MAX_MESSAGE_COUNT - 2), "turn_id": None,
    }


def test_unknown_and_expired_user_message_appends_do_not_expose_session_content() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_model_session_store(clock=clock.now)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(create_model_agent(FakeGenerator(), store))
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        unknown = client.post(
            "/api/v1/agents/kochwiki/sessions/missing/messages", json={"text": "Hello"}
        )
        created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
        clock.value = datetime.fromisoformat(created["expires_at"])

        expired = client.post(
            f"/api/v1/agents/kochwiki/sessions/{created['session_id']}/messages",
            json={"text": "Too late"},
        )
        read = client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}")

        assert unknown.status_code == 404
        assert unknown.json() == {"detail": "Session not found", "kind": "unknown"}
        assert expired.status_code == 410
        assert expired.json() == {"detail": "Session expired", "kind": "expired"}
        assert "messages" not in expired.json()
        assert read.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_user_message_append_and_read_preserve_the_fixed_expiry() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_model_session_store(clock=clock.now)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(create_model_agent(FakeGenerator(), store))
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
        clock.value += timedelta(minutes=10)

        appended = client.post(
            f"/api/v1/agents/kochwiki/sessions/{created['session_id']}/messages",
            json={"text": "Still active"},
        )
        read = client.get(f"/api/v1/agents/kochwiki/sessions/{created['session_id']}")

        assert appended.status_code == 201
        assert read.status_code == 200
        assert read.json()["expires_at"] == created["expires_at"]
    finally:
        app.dependency_overrides.clear()


def test_turn_endpoint_returns_and_stores_assistant_reply(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "  question  "})

    response = observe_turn(client, f"{session_url}/turns")
    read = client.get(session_url)

    assert response.status_code == 200
    assert response.json()["message"] == {
        "role": "assistant",
        "text": "Test reply",
        "turn_id": response.json()["turn_id"],
    }
    assert response.json()["artifacts"] == []
    assert response.json()["turn_id"]
    generation_request = fake_generator.calls[0]
    assert generation_request.input_items[-1] == {"role": "user", "content": "  question  "}
    recipe_context = generation_request.input_items[0]["content"]
    assert isinstance(recipe_context, str)
    assert '"name":"Overnight oats"' in recipe_context
    assert '"name":"Oats"' in recipe_context
    assert "availability_reference_index" not in recipe_context
    assert generation_request.instructions == CONVERSATION_INSTRUCTIONS
    assert "register_recipe_proposal" not in generation_request.instructions
    assert generation_request.tools == ()
    assert read.json()["messages"] == [
        {"role": "user", "text": "  question  ", "turn_id": None},
        {
            "role": "assistant",
            "text": "Test reply",
            "turn_id": response.json()["turn_id"],
        },
    ]


@pytest.mark.parametrize("missing", ["openai_api_key", "kochwiki_openai_model", "kochwiki_mcp_url"])
def test_kochwiki_agent_requires_every_setting(missing: str) -> None:
    values = {
        "openai_api_key": "test-key",
        "kochwiki_openai_model": "test-model",
        "kochwiki_mcp_url": "https://kochwiki.test/mcp/",
    }
    values[missing] = None
    agents = configure_agents(Settings(_env_file=None, **values))
    assert agents.kochwiki.agent is None
    assert agents.demo.agent is not None
    assert agents.demo.agent.create({}, owner="test:user").session_id


def test_locally_valid_kochwiki_configuration_constructs_agent_without_remote_probe() -> None:
    agents = configure_agents(Settings(
        _env_file=None,
        openai_api_key="test-key",
        kochwiki_openai_model="test-model",
        kochwiki_mcp_url="https://kochwiki.test/mcp/",
    ))
    try:
        assert agents.kochwiki.agent is not None
        assert agents.demo.agent is not None
        assert agents.demo.agent.create(None, owner="test:user").session_id
    finally:
        asyncio.run(agents.close())


def test_all_recipe_endpoints_report_unavailable() -> None:
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(None)
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        prefix = "/api/v1/agents/kochwiki/sessions"
        responses = [
            client.post(prefix, json={"input": valid_request()}),
            client.post(prefix),
            client.get(f"{prefix}/missing"),
            client.post(f"{prefix}/missing/messages", json={"text": "question"}),
            client.post(f"{prefix}/missing/messages"),
            client.post(f"{prefix}/missing/turns"),
        ]
        assert all(response.status_code == 503 for response in responses)
        assert all(response.json() == {"detail": "Agent unavailable", "kind": "agent_unavailable"} for response in responses)
    finally:
        app.dependency_overrides.clear()


def test_turn_endpoint_reports_unknown_and_not_ready(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    unknown = client.post("/api/v1/agents/kochwiki/sessions/missing/turns")
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    not_ready = client.post(f"{session_url}/turns")

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Session not found", "kind": "unknown"}
    assert not_ready.status_code == 409
    assert not_ready.json() == {"detail": "Session is not ready for a turn", "kind": "not_ready"}
    assert fake_generator.calls == []


def test_turn_endpoint_reports_generation_failure_without_appending(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "question"})
    fake_generator.fail = True

    response = observe_turn(client, f"{session_url}/turns")

    assert response.status_code == 502
    assert response.json()["kind"] == "generation_failed"
    assert response.json()["turn_id"]
    assert client.get(session_url).json()["messages"] == [{"role": "user", "text": "question", "turn_id": None}]


def test_turn_endpoint_rejects_reply_after_new_message(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "first"})

    def append_another_message() -> None:
        transport = kochwiki_registry_for_test["kochwiki"]
        assert isinstance(transport, AgentTransport)
        blocked = transport.append(session_url.rsplit("/", 1)[1], "second", "test:user")
        assert blocked.status_code == 409
        assert json.loads(blocked.body) == {"detail": "Session is busy", "kind": "busy"}

    kochwiki_registry_for_test = app.dependency_overrides[get_agent_registry]()
    fake_generator.before_return = append_another_message

    response = observe_turn(client, f"{session_url}/turns")

    assert response.status_code == 200
    assert client.get(session_url).json()["messages"] == [
        {"role": "user", "text": "first", "turn_id": None},
        {
            "role": "assistant",
            "text": "Test reply",
            "turn_id": response.json()["turn_id"],
        },
    ]


def test_turn_endpoint_reports_expiry_during_generation(fake_generator: FakeGenerator) -> None:
    clock = MutableClock(datetime(2026, 9, 13, 10, 30, tzinfo=UTC))
    store = new_model_session_store(clock=clock.now)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(create_model_agent(fake_generator, store))
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
        session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
        client.post(f"{session_url}/messages", json={"text": "question"})
        fake_generator.before_return = lambda: setattr(
            clock, "value", datetime.fromisoformat(created["expires_at"])
        )

        response = observe_turn(client, f"{session_url}/turns")

        assert response.status_code == 404
        assert response.json()["kind"] == "unknown"
        assert client.get(session_url).status_code == 404
    finally:
        app.dependency_overrides.pop(get_agent_registry, None)


def test_turn_endpoint_uses_reserved_assistant_capacity(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    for index in range(MAX_MESSAGE_COUNT - 1):
        assert client.post(f"{session_url}/messages", json={"text": str(index)}).status_code == 201

    response = observe_turn(client, f"{session_url}/turns")
    answered = client.get(session_url)
    further_message = client.post(f"{session_url}/messages", json={"text": "one too many"})
    further_turn = observe_turn(client, f"{session_url}/turns")

    assert response.status_code == 200
    assert response.json()["message"] == {
        "role": "assistant",
        "text": "Test reply",
        "turn_id": response.json()["turn_id"],
    }
    assert answered.status_code == 200
    assert len(answered.json()["messages"]) == MAX_MESSAGE_COUNT
    assert further_message.status_code == 409
    assert further_turn.status_code == 200
    assert len(fake_generator.calls) == 1


def test_unknown_retired_tool_and_failed_final_keep_retry_stable(
    client: TestClient, fake_generator: FakeGenerator
) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
    session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
    client.post(f"{session_url}/messages", json={"text": "Propose one"})
    arguments = "{}"
    fake_generator.responses = [
        AgenticGenerationResponse(
            output_items=({"type": "function_call", "call_id": "call_1",
                           "name": "register_recipe_proposal", "arguments": arguments},),
            tool_calls=(AgenticToolCall("call_1", "register_recipe_proposal", arguments),),
            text=None,
        ),
        AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": ""},), (), None),
    ]
    first = observe_turn(client, f"{session_url}/turns")
    retry = observe_turn(client, f"{session_url}/turns")
    read = client.get(session_url)

    assert first.status_code == retry.status_code == 502
    assert first.json() == retry.json()
    assert first.json() == {
        "detail": "Turn generation failed", "kind": "generation_failed", "turn_id": first.json()["turn_id"]
    }
    assert len(fake_generator.calls) == 2
    assert fake_generator.calls[0].tools == ()
    tool_output = fake_generator.calls[1].input_items[-1]["output"]
    assert isinstance(tool_output, str)
    assert json.loads(tool_output) == {"kind": "rejected", "reason": "unknown_tool"}
    assert read.json()["artifacts"] == []
    assert read.json()["terminal_turn_id"] == first.json()["turn_id"]
    assert read.json()["messages"] == [{"role": "user", "text": "Propose one", "turn_id": None}]


def test_session_history_reports_expiry_then_unknown() -> None:
    clock = MutableClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
    store = new_model_session_store(clock=clock.now)
    app.dependency_overrides[get_agent_registry] = lambda: kochwiki_registry(create_model_agent(FakeGenerator(), store))
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
        created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": valid_request()}).json()
        session_url = f"/api/v1/agents/kochwiki/sessions/{created['session_id']}"
        clock.value = datetime.fromisoformat(created["expires_at"])

        expired = client.get(session_url)
        unknown = client.get(session_url)

        assert expired.status_code == 410
        assert expired.json() == {"detail": "Session expired", "kind": "expired"}
        assert unknown.status_code == 404
        assert unknown.json() == {"detail": "Session not found", "kind": "unknown"}
    finally:
        app.dependency_overrides.clear()


JSON_CAPABILITY = {
    "type": "json", "description": "Show structured data deliberately",
    "titleDescription": "Use a short label describing the data.",
    "subtitleDescription": "Omit unless a secondary label is useful.",
    "payloadSchema": {"type": "object", "properties": {"value": {}},
                      "required": ["value"], "additionalProperties": False},
}


def presentation_response(arguments: object) -> AgenticGenerationResponse:
    call = AgenticToolCall("presentation-call", "present_artifact", json.dumps(arguments))
    return AgenticGenerationResponse(({
        "type": "function_call", "call_id": call.call_id,
        "name": call.name, "arguments": call.arguments,
    },), (call,), None)


def test_advertised_presentation_is_validated_published_and_retained(client: TestClient, fake_generator: FakeGenerator) -> None:
    capability = {**JSON_CAPABILITY, "metadataSchema": {"type": "object",
        "properties": {"reference": {"type": "string"}}, "additionalProperties": False}}
    metadata = {"reference": "stored-object"}
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {
        "context": {"selected": "Oats"}, "artifactCapabilities": [capability],
    }})
    session_id = created.json()["session_id"]
    base = f"/api/v1/agents/kochwiki/sessions/{session_id}"
    client.post(base + "/messages", json={"text": "Show the ingredient"})
    fake_generator.responses = [
        presentation_response({"type": "missing", "title": "Ingredient", "payload": {"value": {}}}),
        presentation_response({"type": "json", "title": "Ingredient", "payload": {"wrong": 1}}),
        presentation_response({"type": "json", "title": "Ingredient", "subtitle": "Example brand", "payload": {"value": {"name": "Oats"}}, "metadata": metadata}),
    ]
    response = observe_turn(client, base + "/turns", json_body={})
    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["type"] == "json"
    assert artifacts[0]["payload"] == {"title": "Ingredient", "subtitle": "Example brand", "payload": {"value": {"name": "Oats"}}, "metadata": metadata}
    assert artifacts[0]["order"] == 11
    assert artifacts[0]["artifact_id"]
    assert artifacts[0]["turn_id"] == response.json()["turn_id"]
    assert client.get(base).json()["artifacts"] == artifacts
    request = fake_generator.calls[0]
    assert [tool["name"] for tool in request.tools] == ["present_artifact"]
    assert "Show structured data deliberately" in request.instructions
    assert "payloadSchema" in request.instructions
    assert JSON_CAPABILITY["titleDescription"] in request.instructions
    assert JSON_CAPABILITY["subtitleDescription"] in request.instructions
    outputs = [json.loads(str(item["output"])) for item in fake_generator.calls[-1].input_items
               if item.get("type") == "function_call_output"]
    assert [item.get("reason", item["kind"]) for item in outputs] == ["unsupported_type", "invalid_payload", "presented"]
    assert "payload" not in outputs[-1]
    # A later turn receives the same presentation capability.
    client.post(base + "/messages", json={"text": "Continue"})
    assert observe_turn(client, base + "/turns", json_body={}).status_code == 200
    assert [tool["name"] for tool in fake_generator.calls[-1].tools] == ["present_artifact"]


def test_failed_turn_retains_completed_presentations(client: TestClient, fake_generator: FakeGenerator) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {
        "context": {}, "artifactCapabilities": [JSON_CAPABILITY],
    }})
    base = "/api/v1/agents/kochwiki/sessions/" + created.json()["session_id"]
    client.post(base + "/messages", json={"text": "Show data"})
    presentation = presentation_response({"type": "json", "title": "Data", "payload": {"value": [1, None]}})
    update = {"type": "message", "role": "assistant", "phase": "commentary", "content": "Preparing data."}
    fake_generator.responses = [
        AgenticGenerationResponse((update, *presentation.output_items), presentation.tool_calls, "Preparing data."),
        AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": ""},), (), ""),
    ]
    assert observe_turn(client, base + "/turns", json_body={}).status_code == 502
    snapshot = client.get(base).json()
    assert len(snapshot["artifacts"]) == 1
    assert snapshot["artifacts"][0]["payload"]["payload"] == {"value": [1, None]}
    assert len(snapshot["messages"]) == 1
    assert snapshot["terminal_turn_kind"] == "generation_failed"
    assert [item["kind"] for item in snapshot["timeline"]] == ["message", "intermediate", "tool", "artifact", "failure"]
    assert snapshot["timeline"][1]["text"] == "Preparing data."
    assert snapshot["timeline"][2]["name"] == "present_artifact"
    assert snapshot["timeline"][2]["status"] == "completed"
    assert snapshot["timeline"][3]["artifact_id"] == snapshot["artifacts"][0]["artifact_id"]
    assert "arguments" not in snapshot["timeline"][2]
    assert "output" not in snapshot["timeline"][2]
    assert observe_turn(client, base + "/turns", json_body={}).status_code == 502
    assert len(fake_generator.calls) == 2


def test_completed_turn_separates_commentary_from_standalone_answer(client: TestClient, fake_generator: FakeGenerator) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {"context": {}}}).json()
    base = "/api/v1/agents/kochwiki/sessions/" + created["session_id"]
    client.post(base + "/messages", json={"text": "Check"})
    fake_generator.responses = [AgenticGenerationResponse((
        {"type": "message", "role": "assistant", "phase": "commentary", "content": "Checking."},
        {"type": "message", "role": "assistant", "phase": "final_answer", "content": "Complete answer."},
    ), (), "Checking.Complete answer.")]
    response = observe_turn(client, base + "/turns", json_body={})
    assert response.status_code == 200
    result = response.json()
    assert result["message"]["text"] == "Complete answer."
    assert [item["kind"] for item in result["timeline"]] == ["intermediate", "message"]
    snapshot = client.get(base).json()
    assert snapshot["timeline"][1:] == result["timeline"]
    assert [item["text"] for item in snapshot["messages"]] == ["Check", "Complete answer."]


def test_no_capabilities_means_no_presentation_tool(client: TestClient, fake_generator: FakeGenerator) -> None:
    created = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {"context": {}}})
    base = "/api/v1/agents/kochwiki/sessions/" + created.json()["session_id"]
    client.post(base + "/messages", json={"text": "Hi"})
    assert observe_turn(client, base + "/turns", json_body={}).status_code == 200
    assert fake_generator.calls[0].tools == ()


@pytest.mark.parametrize("capabilities", [
    [JSON_CAPABILITY, JSON_CAPABILITY],
    [{**JSON_CAPABILITY, "payloadSchema": {"type": "not-a-type"}}],
    [{**JSON_CAPABILITY, "payloadSchema": {"$ref": "https://example.test/schema"}}],
    [{**JSON_CAPABILITY, "payloadSchema": {"$schema": "http://json-schema.org/draft-07/schema#"}}],
    [{**JSON_CAPABILITY, "metadataSchema": {"type": "not-a-type"}}],
    [{**JSON_CAPABILITY, "metadataSchema": {"$ref": "https://example.test/schema"}}],
])
def test_invalid_capabilities_reject_session_creation(client: TestClient, capabilities: object) -> None:
    response = client.post("/api/v1/agents/kochwiki/sessions", json={"input": {
        "context": {}, "artifactCapabilities": capabilities,
    }})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][:3] == ["body", "input", "artifactCapabilities"]
