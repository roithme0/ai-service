import asyncio
from collections.abc import Iterator
from typing import cast, get_args
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.testclient import TestClient
from turn_observation import observe_turn
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.demo.agent import create_demo_agent
from app.agents.service import ConfiguredAgentService
from app.sessions.model_sessions import create_model_agent
from app.main import app, handle_http_exception, handle_request_validation
from app.sessions.protocols.http import ConversationTransport
from app.sessions.http import AgentConfiguration, AgentTransport, _demo_issue, _error, _context_issue, get_agent_registry
from app.sessions.models.http import ErrorResponse, SessionErrorKind, ValidationErrorResponse
from test_model_session_http import FakeGenerator, valid_request


@pytest.fixture
def client() -> Iterator[TestClient]:
    registry: dict[str, ConversationTransport | None] = {
        "kochwiki": AgentTransport(create_model_agent(FakeGenerator()), lambda value: value, _context_issue),
        "demo": AgentTransport(create_demo_agent(delay_seconds=0), lambda value: value, _demo_issue),
    }
    app.dependency_overrides[get_agent_registry] = lambda: registry
    try:
        with TestClient(app, headers={"X-Application-User": "test:user"}) as running:
            yield running
    finally:
        app.dependency_overrides.clear()


def test_configuration_registry_matches_published_names() -> None:
    assert set(get_agent_registry()) == set(AgentConfiguration)


@pytest.mark.parametrize("identity", [None, "", "alice", ":42", "source:", "source:42:extra", " source:42", "source:two words", "source:42 "])
def test_invalid_identity_rejects_every_conversation_operation_without_access(
    client: TestClient, identity: str | None,
) -> None:
    base = "/api/v1/agents/demo/sessions"
    session_id = client.post(base, json={}).json()["session_id"]
    client.headers.clear()
    headers = {} if identity is None else {"X-Application-User": identity}
    with (
        patch.object(AgentTransport, "create") as create,
        patch.object(AgentTransport, "read") as read,
        patch.object(AgentTransport, "append") as append,
        patch.object(AgentTransport, "turn") as turn,
        patch.object(AgentTransport, "observe") as observe,
    ):
        for method, path, body in (
            ("POST", base, {}),
            ("GET", f"{base}/{session_id}", None),
            ("POST", f"{base}/{session_id}/messages", {"text": "Must not append"}),
            ("POST", f"{base}/{session_id}/turns", None),
            ("GET", f"{base}/{session_id}/turns/missing/events", None),
        ):
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 422
            error = ValidationErrorResponse.model_validate_json(response.text)
            assert error.kind == "request_validation"
            assert error.detail[0].loc == ("header", "X-Application-User")
        for operation in (create, read, append, turn, observe):
            operation.assert_not_called()


@pytest.mark.parametrize("identity", ["kochwiki:42", "demo:default", "unknown-source:user", "42:alice"])
def test_identity_accepts_unrestricted_prefixes_without_user_lookup(client: TestClient, identity: str) -> None:
    assert client.post(
        "/api/v1/agents/demo/sessions", json={}, headers={"X-Application-User": identity},
    ).status_code == 201


@pytest.mark.parametrize("configuration", ["demo", "kochwiki"])
@pytest.mark.parametrize("other_owner", ["test:other", "another-source:user", "test:User"])
def test_other_owner_cannot_access_or_change_conversation(
    client: TestClient, configuration: str, other_owner: str,
) -> None:
    base = f"/api/v1/agents/{configuration}/sessions"
    body = {} if configuration == "demo" else {"input": valid_request()}
    session_id = client.post(base, json=body).json()["session_id"]
    assert client.post(f"{base}/{session_id}/messages", json={"text": "Private message"}).status_code == 201
    before = client.get(f"{base}/{session_id}").json()
    with (
        patch.object(ConfiguredAgentService, "read") as read,
        patch.object(ConfiguredAgentService, "append_user_message") as append,
        patch.object(ConfiguredAgentService, "start_turn") as start,
        patch.object(ConfiguredAgentService, "observe") as observe,
        patch.object(ConfiguredAgentService, "observation_available") as available,
    ):
        for method, suffix, payload in (
            ("GET", "", None),
            ("POST", "/messages", {"text": "Intrusion"}),
            ("POST", "/turns", None),
            ("GET", "/turns/private-turn/events", None),
        ):
            denied = client.request(method, f"{base}/{session_id}{suffix}", json=payload,
                                    headers={"X-Application-User": other_owner})
            missing = client.request(method, f"{base}/missing{suffix}", json=payload)
            assert denied.status_code == missing.status_code == 404
            assert denied.json() == missing.json()
            assert denied.headers["content-type"] == "application/json"
        for operation in (read, append, start, observe, available):
            operation.assert_not_called()
    assert client.get(f"{base}/{session_id}").json() == before
    assert client.post(f"{base}/{session_id}/messages", json={"text": "Still mine"}).status_code == 201
    other_session = client.post(base, json=body, headers={"X-Application-User": other_owner}).json()["session_id"]
    assert client.get(f"{base}/{other_session}").status_code == 404
    assert client.get(f"{base}/{other_session}", headers={"X-Application-User": other_owner}).status_code == 200


def test_every_session_error_kind_has_a_valid_response() -> None:
    for kind in cast(tuple[SessionErrorKind, ...], get_args(SessionErrorKind)):
        response = _error(kind)
        body = ErrorResponse.model_validate_json(response.body)
        assert response.status_code >= 400
        assert body.kind == kind
        assert body.detail


def test_registry_and_creation_envelopes(client: TestClient) -> None:
    base = "/api/v1/agents"
    unknown = client.post(f"{base}/missing/sessions", json={})
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Agent configuration not found", "kind": "unknown_configuration"}

    for value in ({}, {"input": None}, {"input": {}}):
        assert client.post(f"{base}/demo/sessions", json=value).status_code == 201
    assert client.post(f"{base}/demo/sessions", json=[]).json() == {
        "kind": "invalid_input",
        "detail": [{"loc": ["body"], "msg": "request must be an object", "type": "model_type"}],
    }
    for value, location in (
        ({"input": {"tools": []}}, ["input"]),
        ({"input": []}, ["input"]),
        ({"input": {}, "model": "override"}, ["model"]),
    ):
        rejected = client.post(f"{base}/demo/sessions", json=value)
        assert rejected.status_code == 422
        assert rejected.json()["detail"][0]["loc"] == ["body", *location]
    missing_recipe = client.post(f"{base}/kochwiki/sessions", json={})
    assert missing_recipe.status_code == 422
    assert missing_recipe.json()["detail"][0]["loc"][:2] == ["body", "input"]
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


def test_framework_http_errors_use_shared_envelope_and_preserve_headers(client: TestClient) -> None:
    response = client.put("/api/v1/agents/demo/sessions")
    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed", "kind": "method_not_allowed"}
    assert "POST" in response.headers["allow"]

    http_app = FastAPI()
    http_app.add_exception_handler(StarletteHTTPException, handle_http_exception)

    @http_app.get("/protected")
    def protected() -> None:
        raise StarletteHTTPException(401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})

    unauthorized = TestClient(http_app).get("/protected")
    assert unauthorized.json() == {"detail": "Authentication required", "kind": "http_error"}
    assert unauthorized.headers["www-authenticate"] == "Bearer"


def test_unexpected_failure_has_generic_body_and_propagates_for_logging(client: TestClient) -> None:
    with patch.object(AgentTransport, "create", side_effect=RuntimeError("private failure detail")):
        response = TestClient(app, raise_server_exceptions=False, headers={"X-Application-User": "test:user"}).post("/api/v1/agents/demo/sessions", json={})
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal Server Error", "kind": "internal_error"}
        assert "private failure detail" not in response.text
        with pytest.raises(RuntimeError, match="private failure detail"):
            client.post("/api/v1/agents/demo/sessions", json={})


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
    failed_activity: list[dict[str, object]] = []
    for index in range(5):
        message = client.post(f"{session}/messages", json={"text": f"user {index}"})
        assert message.status_code == 201
        assert message.json() == {"role": "user", "text": f"user {index}", "turn_id": None}
        turn = observe_turn(client, f"{session}/turns")
        body = turn.json()
        if index == 2:
            assert turn.status_code == 502
            assert body["kind"] == "generation_failed"
            assert observe_turn(client, f"{session}/turns").json() == body
            failed_history = client.get(session).json()
            assert failed_history["terminal_turn_kind"] == "generation_failed"
            assert len(failed_history["artifacts"]) == 2
            failed_activity = [item for item in failed_history["timeline"] if item["turn_id"] == body["turn_id"]]
            assert [item["kind"] for item in failed_activity] == ["message", "intermediate", "failure"]
            assert "without a final answer" in failed_activity[1]["text"]
            assert client.get(session).json()["timeline"] == failed_history["timeline"]
            continue
        assert turn.status_code == 200
        assert body["kind"] == "completed"
        assert body["message"]["role"] == "assistant"
        assert body["message"]["turn_id"] == body["turn_id"]
        assert "script" in body["message"]["text"].lower() or "skript" in body["message"]["text"].lower()
        texts.append(body["message"]["text"])
        if index == 1:
            assert len(body["artifacts"]) == 2
            assert [item["kind"] for item in body["timeline"]] == [
                "intermediate", "tool", "artifact", "intermediate", "tool", "artifact", "intermediate", "tool", "message",
            ]
            assert "single greeting" in body["timeline"][0]["text"]
            assert "30 greetings" in body["timeline"][3]["text"]
            assert [item["name"] for item in body["timeline"] if item["kind"] == "tool"] == [
                "create_greeting", "create_greetings", "create_greeting",
            ]
            assert [item["status"] for item in body["timeline"] if item["kind"] == "tool"] == ["completed", "completed", "failed"]
            assert "failed validation" in body["message"]["text"]
            projected = [item for item in client.get(session).json()["timeline"]
                         if item["turn_id"] == body["turn_id"] and not (item["kind"] == "message" and item["role"] == "user")]
            assert projected == body["timeline"]
            greeting, greetings = body["artifacts"]
            assert greeting["type"] == "demo.greeting"
            assert greeting["payload"] == {"message": "Hello, World!"}
            assert greeting["order"] == 9
            assert greeting["turn_id"] == body["turn_id"]
            assert greetings["type"] == "demo.greetings"
            assert greetings["payload"] == {"messages": [f"Hello, Visitor {number}!" for number in range(1, 31)]}
            assert greetings["order"] == 14
            assert greetings["turn_id"] == body["turn_id"]
            artifacts.extend((greeting, greetings))
        else:
            assert body["artifacts"] == []
    history = client.get(session).json()
    assert len(history["messages"]) == 9
    assert history["messages"][0] == {"role": "user", "text": "user 0", "turn_id": None}
    assert history["artifacts"] == artifacts
    assert [item for item in history["timeline"] if item["turn_id"] == failed_activity[0]["turn_id"]] == failed_activity
    assert "source" not in history
    fresh = client.post(base, json={}).json()
    fresh_session = f"{base}/{fresh['session_id']}"
    client.post(f"{fresh_session}/messages", json={"text": "again"})
    assert observe_turn(client, f"{fresh_session}/turns").json()["message"]["text"] == texts[0]


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
    assert turn_path["post"]["responses"]["202"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/AcceptedTurnResponse"
    )
    assert "turn_id" in schemas["UserMessageResponse"]["required"]
    assert schemas["UserMessageResponse"]["properties"]["turn_id"]["type"] == "null"
    assert schemas["SessionSnapshotResponse"]["properties"]["messages"]["items"]["discriminator"]["propertyName"] == "role"
    assert schemas["AcceptedTurnResponse"]["properties"]["kind"]["const"] == "accepted"


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
        "detail": [{"loc": ["body", "extra"], "msg": "extra field not permitted", "type": "extra_forbidden"}],
        "kind": "invalid_message",
    }
    assert client.post(f"{session}/turns", content="null", headers={"content-type": "application/json"}).json() == {
        "detail": [{"loc": ["body"], "msg": "request must be an object", "type": "model_type"}],
        "kind": "invalid_input",
    }
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
        base: {404: "ErrorResponse", 405: "HttpErrorResponse", 422: "ValidationErrorResponse", 500: "HttpErrorResponse", 503: "ErrorResponse"},
        f"{base}/{{session_id}}": {
            404: "ErrorResponse", 405: "HttpErrorResponse", 410: "ErrorResponse", 422: "ValidationErrorResponse",
            500: "HttpErrorResponse", 503: "ErrorResponse",
        },
        f"{base}/{{session_id}}/messages": {
            404: "ErrorResponse", 405: "HttpErrorResponse", 409: "ErrorResponse", 410: "ErrorResponse",
            422: "ValidationErrorResponse", 500: "HttpErrorResponse", 503: "ErrorResponse",
        },
        f"{base}/{{session_id}}/turns": {
            404: "ErrorResponse", 405: "HttpErrorResponse", 409: "ErrorResponse", 410: "ErrorResponse",
            422: "ValidationErrorResponse", 500: "HttpErrorResponse", 502: "ErrorResponse", 503: "ErrorResponse",
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
    assert {"method_not_allowed", "http_error", "internal_error"} <= set(error_schema["properties"]["kind"]["enum"])
    for status in (405, 500):
        assert paths["/"]["get"]["responses"][str(status)]["content"]["application/json"]["schema"]["$ref"] == (
            "#/components/schemas/HttpErrorResponse"
        )
    validation_schema = document["components"]["schemas"]["ValidationErrorResponse"]
    item_schema = document["components"]["schemas"]["ValidationDetail"]
    assert set(validation_schema["required"]) == {"detail", "kind"}
    assert validation_schema["properties"]["detail"]["minItems"] == 1
    assert set(item_schema["required"]) == {"loc", "msg", "type"}
    assert item_schema["additionalProperties"] is False

    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"detail": "Missing", "kind": "unexpected"})
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"kind": "unknown"})
    with pytest.raises(ValidationError):
        ValidationErrorResponse.model_validate({"kind": "invalid_input", "detail": []})
    with pytest.raises(ValidationError):
        ValidationErrorResponse.model_validate({
            "kind": "invalid_input", "detail": [{"loc": ("body",), "msg": "Invalid", "type": "value_error", "input": "secret"}],
        })


def test_framework_request_validation_uses_public_detail_shape() -> None:
    validation_app = FastAPI()
    validation_app.add_exception_handler(RequestValidationError, handle_request_validation)

    @validation_app.get("/items/{item_id}")
    def read_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    response = TestClient(validation_app).get("/items/not-an-int")
    assert response.status_code == 422
    assert response.json() == {
        "detail": [{"loc": ["path", "item_id"], "msg": "Input should be a valid integer, unable to parse string as an integer", "type": "int_parsing"}],
        "kind": "request_validation",
    }


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
            observe_turn(client, "/api/v1/agents/demo/sessions/session-1/turns")


def test_unavailable_agent_precedes_malformed_body() -> None:
    app.dependency_overrides[get_agent_registry] = lambda: {"kochwiki": None, "demo": None}
    try:
        client = TestClient(app, headers={"X-Application-User": "test:user"})
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers={"X-Application-User": "test:user"}) as client:
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
            assert busy.status_code == 202
            assert busy.json() == (await first_turn).json()
            turn_id = busy.json()["turn_id"]
            client.headers["X-Application-User"] = "test:other"
            for method, suffix, body in (
                ("GET", "", None),
                ("POST", "/messages", {"text": "Another user"}),
                ("POST", "/turns", None),
                ("GET", f"/turns/{turn_id}/events", None),
            ):
                denied = await client.request(method, f"{base}/{first}{suffix}", json=body)
                assert denied.status_code == 404
                assert denied.json()["kind"] == "unknown"
            assert calls == 2
            release.set()
            assert (await first_turn).status_code == 202
            assert (await second_turn).status_code == 202
            client.headers["X-Application-User"] = "test:user"
            for _ in range(100):
                snapshot = (await client.get(f"{base}/{first}")).json()
                if snapshot["terminal_turn_kind"] is not None:
                    break
                await asyncio.sleep(0.01)
            assert snapshot["terminal_turn_kind"] == "completed"
            observed = await client.get(f"{base}/{first}/turns/{turn_id}/events")
            assert observed.status_code == 200
            assert '"kind":"terminal"' in observed.text
            await agent.close()

    try:
        asyncio.run(exercise())
    finally:
        app.dependency_overrides.clear()
