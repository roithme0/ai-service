import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agents.demo import create_demo_agent
from app.agents.recipe import create_recipe_agent
from app.main import app
from app.sessions.http import (
    AgentTransport, ConversationTransport, _demo_issue, _recipe_input,
    _recipe_issue, get_agent_registry,
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


def test_registry_and_creation_envelopes(client: TestClient) -> None:
    base = "/api/v1/agents"
    unknown = client.post(f"{base}/missing/sessions", json={})
    assert unknown.status_code == 404
    assert unknown.json() == {"kind": "unknown_configuration"}

    for value in ({}, {"input": None}, {"input": {}}):
        assert client.post(f"{base}/demo/sessions", json=value).status_code == 201
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
    assert wrong_agent.json() == {"kind": "unknown"}
    assert client.get(f"{base}/kochwiki/sessions/{session_id}").status_code == 200
    assert client.post(f"{base}/kochwiki/sessions/{session_id}/turns", json={"model": "override"}).status_code == 422
    assert client.get(f"{base}/kochwiki/sessions/{session_id}").json()["messages"] == []
    assert client.post("/api/v1/recipe-improvement/sessions", json=valid_request()).status_code == 404
    assert client.get(f"{base}/kochwiki/sessions/{session_id}/proposals/missing").status_code == 404


def test_demo_http_sequence_and_new_session(client: TestClient) -> None:
    base = "/api/v1/agents/demo/sessions"
    created = client.post(base, json={}).json()
    session = f"{base}/{created['session_id']}"
    assert client.post(f"{session}/turns").json() == {"kind": "not_ready"}
    texts: list[str] = []
    for index in range(3):
        message = client.post(f"{session}/messages", json={"text": f"user {index}"})
        assert message.status_code == 201
        turn = client.post(f"{session}/turns")
        assert turn.status_code == 201
        body = turn.json()
        assert body["kind"] == "completed"
        assert "script" in body["message"]["text"].lower() or "skript" in body["message"]["text"].lower()
        texts.append(body["message"]["text"])
        if index == 1:
            assert len(body["artifacts"]) == 1
            artifact = body["artifacts"][0]
            assert artifact["type"] == "demo.greeting"
            assert artifact["payload"] == {"message": "Hello, World!"}
            assert artifact["order"] == 1
            assert artifact["turn_id"] == body["turn_id"]
        else:
            assert body["artifacts"] == []
    history = client.get(session).json()
    assert len(history["messages"]) == 6
    assert history["artifacts"] == [artifact]
    assert "source" not in history
    fresh = client.post(base, json={}).json()
    fresh_session = f"{base}/{fresh['session_id']}"
    client.post(f"{fresh_session}/messages", json={"text": "again"})
    assert client.post(f"{fresh_session}/turns").json()["message"]["text"] == texts[0]


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
        assert all(response.json() == {"kind": "agent_unavailable"} for response in responses)
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
