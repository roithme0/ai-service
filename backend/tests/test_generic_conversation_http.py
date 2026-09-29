import asyncio
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.exceptions import ResponseValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.demo import create_demo_agent
from app.agents.recipe import create_recipe_agent
from app.main import app
from app.sessions.http import (
    AgentConfiguration, AgentTransport, ConversationTransport, ErrorResponse, InvalidInputResponse,
    _demo_issue, _recipe_input, _recipe_issue, get_agent_registry,
)
from test_recipe_improvement_session_http import FakeGenerator, FakeResolver, valid_request


@pytest.fixture
def client() -> Iterator[TestClient]:
    registry: dict[str, ConversationTransport | None] = {
        "kochwiki": AgentTransport(create_recipe_agent(FakeGenerator(), FakeResolver()), _recipe_input, _recipe_issue),
        "demo": AgentTransport(create_demo_agent(delay_seconds=0), lambda value: value, _demo_issue),
    }
    app.dependency_overrides[get_agent_registry] = lambda: registry
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_configuration_registry_matches_published_names() -> None:
    assert set(get_agent_registry()) == set(AgentConfiguration)


def test_registry_and_creation_envelopes(client: TestClient) -> None:
    base = "/api/v1/agents"
    unknown = client.post(f"{base}/missing/sessions", json={})
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Agent configuration not found", "kind": "unknown_configuration"}

    for value in ({}, {"input": None}, {"input": {}}):
        assert client.post(f"{base}/demo/sessions", json=value).status_code == 201
    assert client.post(f"{base}/demo/sessions", json=[]).json() == {
        "kind": "invalid_input",
        "issues": [{"location": [], "message": "request must be an object"}],
    }
    for value, location in (
        ({"input": {"tools": []}}, ["input"]),
        ({"input": []}, ["input"]),
        ({"input": {}, "model": "override"}, ["model"]),
    ):
        rejected = client.post(f"{base}/demo/sessions", json=value)
        assert rejected.status_code == 422
        assert rejected.json()["issues"][0]["location"] == location
    missing_recipe = client.post(f"{base}/kochwiki/sessions", json={})
    assert missing_recipe.status_code == 422
    assert missing_recipe.json()["issues"][0]["location"][0] == "input"
    recipe = client.post(f"{base}/kochwiki/sessions", json={"input": valid_request()})
    assert recipe.status_code == 201
    session_id = recipe.json()["session_id"]
    wrong_agent = client.get(f"{base}/demo/sessions/{session_id}")
    assert wrong_agent.status_code == 404
    assert wrong_agent.json() == {"detail": "Session not found", "kind": "unknown"}
    assert client.get(f"{base}/kochwiki/sessions/{session_id}").status_code == 200
    assert client.post(f"{base}/kochwiki/sessions/{session_id}/turns", json={"model": "override"}).status_code == 422
    assert client.get(f"{base}/kochwiki/sessions/{session_id}").json()["messages"] == []
    unmatched = client.post("/api/v1/recipe-improvement/sessions", json=valid_request())
    assert unmatched.status_code == 404
    assert unmatched.json() == {"detail": "Not Found", "kind": "not_found"}
    assert set(unmatched.json()) == set(wrong_agent.json())
    assert client.get(f"{base}/kochwiki/sessions/{session_id}/proposals/missing").json() == unmatched.json()


def test_demo_http_sequence_and_new_session(client: TestClient) -> None:
    base = "/api/v1/agents/demo/sessions"
    creation = client.post(base, json={})
    assert creation.status_code == 201
    created = creation.json()
    assert set(created) == {"session_id", "expires_at"}
    assert created["expires_at"].endswith("+00:00")
    session = f"{base}/{created['session_id']}"
    assert client.post(f"{session}/turns").json() == {"detail": "Session is not ready for a turn", "kind": "not_ready"}
    texts: list[str] = []
    artifacts: list[dict[str, object]] = []
    for index in range(5):
        message = client.post(f"{session}/messages", json={"text": f"user {index}"})
        assert message.status_code == 201
        assert message.json() == {"role": "user", "text": f"user {index}", "turn_id": None}
        turn = client.post(f"{session}/turns")
        body = turn.json()
        if index == 2:
            assert turn.status_code == 502
            assert body["kind"] == "generation_failed"
            assert client.post(f"{session}/turns").json() == body
            failed_history = client.get(session).json()
            assert failed_history["terminal_turn_kind"] == "generation_failed"
            assert len(failed_history["artifacts"]) == 2
            continue
        assert turn.status_code == 201
        assert body["kind"] == "completed"
        assert body["message"]["role"] == "assistant"
        assert body["message"]["turn_id"] == body["turn_id"]
        assert "script" in body["message"]["text"].lower() or "skript" in body["message"]["text"].lower()
        texts.append(body["message"]["text"])
        if index == 1:
            assert len(body["artifacts"]) == 2
            greeting, greetings = body["artifacts"]
            assert greeting["type"] == "demo.greeting"
            assert greeting["payload"] == {"message": "Hello, World!"}
            assert greeting["order"] == 1
            assert greeting["turn_id"] == body["turn_id"]
            assert greetings["type"] == "demo.greetings"
            assert greetings["payload"] == {"messages": [f"Hello, Visitor {number}!" for number in range(1, 31)]}
            assert greetings["order"] == 2
            assert greetings["turn_id"] == body["turn_id"]
            artifacts.extend((greeting, greetings))
        else:
            assert body["artifacts"] == []
    history = client.get(session).json()
    assert len(history["messages"]) == 9
    assert history["messages"][0] == {"role": "user", "text": "user 0", "turn_id": None}
    assert history["artifacts"] == artifacts
    assert "source" not in history
    fresh = client.post(base, json={}).json()
    fresh_session = f"{base}/{fresh['session_id']}"
    client.post(f"{fresh_session}/messages", json={"text": "again"})
    assert client.post(f"{fresh_session}/turns").json()["message"]["text"] == texts[0]


def test_success_schemas_are_published(client: TestClient) -> None:
    document = client.get("/api/openapi.json").json()
    creation_path = document["paths"]["/api/v1/agents/{configuration}/sessions"]
    path = document["paths"]["/api/v1/agents/{configuration}/sessions/{session_id}"]
    append_path = document["paths"]["/api/v1/agents/{configuration}/sessions/{session_id}/messages"]
    turn_path = document["paths"]["/api/v1/agents/{configuration}/sessions/{session_id}/turns"]
    schemas = document["components"]["schemas"]

    assert creation_path["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/SessionCreationResponse"
    )
    assert path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/SessionSnapshotResponse"
    )
    assert append_path["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/UserMessageResponse"
    )
    assert turn_path["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/CompletedTurnResponse"
    )
    assert "turn_id" in schemas["UserMessageResponse"]["required"]
    assert schemas["UserMessageResponse"]["properties"]["turn_id"]["type"] == "null"
    assert schemas["SessionSnapshotResponse"]["properties"]["messages"]["items"]["discriminator"]["propertyName"] == "role"
    assert schemas["CompletedTurnResponse"]["properties"]["message"]["$ref"] == (
        "#/components/schemas/AssistantMessageResponse"
    )
    assert schemas["CompletedTurnResponse"]["properties"]["kind"]["const"] == "completed"


def test_request_bodies_are_published_and_enforced(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    base = "/api/v1/agents/{configuration}/sessions"
    creation = paths[base]["post"]["requestBody"]
    message = paths[f"{base}/{{session_id}}/messages"]["post"]["requestBody"]
    turn = paths[f"{base}/{{session_id}}/turns"]["post"]["requestBody"]

    for path, method in (
        (base, "post"),
        (f"{base}/{{session_id}}", "get"),
        (f"{base}/{{session_id}}/messages", "post"),
        (f"{base}/{{session_id}}/turns", "post"),
    ):
        configuration = next(
            parameter for parameter in paths[path][method]["parameters"]
            if parameter["name"] == "configuration"
        )
        assert configuration["schema"]["enum"] == ["demo", "kochwiki"]

    creation_schema = creation["content"]["application/json"]["schema"]
    message_schema = message["content"]["application/json"]["schema"]
    turn_schema = turn["content"]["application/json"]["schema"]
    assert creation["required"] is True
    assert creation_schema["additionalProperties"] is False
    assert set(creation_schema["properties"]) == {"input"}
    assert message["required"] is True
    assert message_schema["required"] == ["text"]
    assert message_schema["additionalProperties"] is False
    assert turn["required"] is False
    assert turn_schema["properties"] == {}
    assert turn_schema["additionalProperties"] is False

    session_id = client.post("/api/v1/agents/demo/sessions", json={}).json()["session_id"]
    session = f"/api/v1/agents/demo/sessions/{session_id}"
    assert client.post(f"{session}/messages", json={"text": "Hello", "extra": True}).json() == {
        "detail": "Invalid message", "kind": "invalid_message"
    }
    assert client.post(f"{session}/turns", content="null", headers={"content-type": "application/json"}).status_code == 422
    assert client.post(f"{session}/turns", json={}).json() == {
        "detail": "Session is not ready for a turn", "kind": "not_ready"
    }


def test_error_schemas_are_published_and_reject_invalid_bodies(client: TestClient) -> None:
    document = client.get("/api/openapi.json").json()
    paths = document["paths"]
    base = "/api/v1/agents/{configuration}/sessions"
    for path in (base, f"{base}/{{session_id}}/messages", f"{base}/{{session_id}}/turns"):
        assert paths[path]["post"]["responses"]["422"]["description"] == "Unprocessable Content"
    expected = {
        base: {404: "ErrorResponse", 422: "InvalidInputResponse", 503: "ErrorResponse"},
        f"{base}/{{session_id}}": {404: "ErrorResponse", 410: "ErrorResponse", 503: "ErrorResponse"},
        f"{base}/{{session_id}}/messages": {
            404: "ErrorResponse", 409: "ErrorResponse", 410: "ErrorResponse",
            422: "ErrorResponse", 503: "ErrorResponse",
        },
        f"{base}/{{session_id}}/turns": {
            404: "ErrorResponse", 409: "ErrorResponse", 410: "ErrorResponse",
            422: "InvalidInputResponse", 502: "ErrorResponse", 503: "ErrorResponse",
        },
    }
    for path, responses in expected.items():
        operation = paths[path]["get" if path.endswith("{session_id}") else "post"]
        for status, model in responses.items():
            assert operation["responses"][str(status)]["content"]["application/json"]["schema"]["$ref"] == (
                f"#/components/schemas/{model}"
            )

    error_schema = document["components"]["schemas"]["ErrorResponse"]
    assert set(error_schema["required"]) == {"detail", "kind"}
    assert error_schema["properties"]["detail"]["minLength"] == 1

    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"detail": "Missing", "kind": "unexpected"})
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"kind": "unknown"})
    with pytest.raises(ValidationError):
        InvalidInputResponse.model_validate({"kind": "invalid_input", "issues": [{"location": (), "message": 7}]})


def test_success_bodies_are_validated(client: TestClient) -> None:
    with patch.object(AgentTransport, "create", return_value={"session_id": "session-1"}):
        with pytest.raises(ResponseValidationError):
            client.post("/api/v1/agents/demo/sessions", json={})

    with patch.object(AgentTransport, "read", return_value={"session_id": "session-1"}):
        with pytest.raises(ResponseValidationError):
            client.get("/api/v1/agents/demo/sessions/session-1")

    with patch.object(AgentTransport, "append", return_value={"role": "user", "text": "Hello"}):
        with pytest.raises(ResponseValidationError):
            client.post("/api/v1/agents/demo/sessions/session-1/messages", json={"text": "Hello"})

    with patch.object(AgentTransport, "turn", return_value={"kind": "completed", "turn_id": "turn-1"}):
        with pytest.raises(ResponseValidationError):
            client.post("/api/v1/agents/demo/sessions/session-1/turns")


def test_unavailable_agent_precedes_malformed_body() -> None:
    app.dependency_overrides[get_agent_registry] = lambda: {"kochwiki": None, "demo": None}
    try:
        client = TestClient(app)
        base = "/api/v1/agents/kochwiki/sessions"
        responses = (
            client.post(base, content="bad json", headers={"content-type": "application/json"}),
            client.get(f"{base}/missing"),
            client.post(f"{base}/missing/messages", content="bad json"),
            client.post(f"{base}/missing/turns"),
        )
        assert all(response.status_code == 503 for response in responses)
        assert all(response.json() == {"detail": "Agent unavailable", "kind": "agent_unavailable"} for response in responses)
    finally:
        app.dependency_overrides.clear()


def test_demo_concurrent_sessions_and_busy_turn() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def pause(_seconds: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
        await release.wait()

    agent = create_demo_agent(delay_seconds=0.01, pause=pause)
    app.dependency_overrides[get_agent_registry] = lambda: {
        "demo": AgentTransport(agent, lambda value: value, _demo_issue), "kochwiki": None,
    }

    async def exercise() -> None:
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            base = "/api/v1/agents/demo/sessions"
            first = (await client.post(base, json={})).json()["session_id"]
            second = (await client.post(base, json={})).json()["session_id"]
            for session_id in (first, second):
                assert (await client.post(f"{base}/{session_id}/messages", json={"text": "Hi"})).status_code == 201
            first_turn = asyncio.create_task(client.post(f"{base}/{first}/turns"))
            await asyncio.sleep(0)
            second_turn = asyncio.create_task(client.post(f"{base}/{second}/turns"))
            await asyncio.wait_for(entered.wait(), timeout=2)
            busy = await client.post(f"{base}/{first}/turns")
            assert busy.status_code == 409
            assert busy.json()["kind"] == "busy"
            release.set()
            assert (await first_turn).status_code == 201
            assert (await second_turn).status_code == 201

    try:
        asyncio.run(exercise())
    finally:
        app.dependency_overrides.clear()
