import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter
from pydantic_ai import models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.types import Message
from starlette.requests import ClientDisconnect

from app.agentic.http import ObservationErrorEvent, SessionEvent, SnapshotEvent, create_session_router
from app.agentic.presentation import AcceptedArtifact, PresentedSession, PresentedTurn, ToolActivity
from app.agentic.runner import AgentTurnRunner
from app.agentic.sessions import ObservationOverflowError, SessionNotFoundError
from app.agentic.turns import create_turn_agent


BASE = "/api/v1/agents/test/sessions"
IDENTITY = {"X-Application-User": "test:alice"}
EVENT_ADAPTER = TypeAdapter(SessionEvent)


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def application(runner: AgentTurnRunner) -> FastAPI:
    app = FastAPI()
    app.include_router(create_session_router(lambda: {"test": runner, "unavailable": None}))
    return app


def turns(snapshot: PresentedSession) -> tuple[PresentedTurn, ...]:
    return tuple(item for item in snapshot.history if isinstance(item, PresentedTurn))


class Stream:
    def __init__(self, app: FastAPI, path: str) -> None:
        self.app = app
        self.path = path
        self.messages: asyncio.Queue[Message] = asyncio.Queue()
        self.disconnected = asyncio.Event()
        self.request_sent = False
        self.spec_version = "2.0"

    async def receive(self) -> Message:
        if not self.request_sent:
            self.request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: Message) -> None:
        await self.messages.put(message)

    async def run(self) -> None:
        await self.app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": self.spec_version},
            "http_version": "1.1", "scheme": "http", "method": "GET",
            "path": self.path, "raw_path": self.path.encode(), "query_string": b"",
            "root_path": "", "server": ("test", 80), "client": ("test", 123),
            "headers": [(b"x-application-user", b"test:alice")],
        }, self.receive, self.send)

    async def next_message(self) -> Message:
        return await asyncio.wait_for(self.messages.get(), 5)

    async def event(self) -> SnapshotEvent | ObservationErrorEvent:
        message = await self.next_message()
        assert message["type"] == "http.response.body"
        body = message["body"]
        assert isinstance(body, bytes) and body.startswith(b"data: ") and body.endswith(b"\n\n")
        return EVENT_ADAPTER.validate_json(body[6:-2])

    async def until(self, predicate: Callable[[PresentedSession], bool]) -> PresentedSession:
        async with asyncio.timeout(5):
            while True:
                event = await self.event()
                assert isinstance(event, SnapshotEvent)
                if predicate(event.snapshot):
                    return event.snapshot


@asynccontextmanager
async def stream(app: FastAPI, path: str) -> AsyncIterator[Stream]:
    opened = Stream(app, path)
    task = asyncio.create_task(opened.run())
    try:
        headers = await opened.next_message()
        assert headers["type"] == "http.response.start" and headers["status"] == 200
        assert (b"content-type", b"text/event-stream; charset=utf-8") in headers["headers"]
        yield opened
    finally:
        opened.disconnected.set()
        await asyncio.wait_for(task, 5)


def test_http_admission_live_artifacts_failure_and_multiple_turns() -> None:
    async def exercise() -> None:
        continuing, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not any(isinstance(part, ToolReturnPart) for msg in messages for part in msg.parts):
                return ModelResponse(parts=[TextPart("Working."), ToolCallPart("present_artifact", {
                    "candidate": {"type": "example", "payload": {"title": "Visible", "payload": {}}},
                }, "artifact")])
            continuing.set()
            await release.wait()
            raise RuntimeError("SECRET_PROVIDER_ERROR")

        agent = create_turn_agent(FunctionModel(respond), instructions="SECRET_INSTRUCTIONS")
        runner = AgentTurnRunner(agent)
        app = application(runner)
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers=IDENTITY) as client:
            created = await client.post(BASE, json={
                "initial_context": {"secret": "SECRET_CONTEXT"},
                "artifact_capabilities": [{"type": "example", "description": "Display.", "payloadSchema": {"type": "object"}}],
            })
            assert created.status_code == 201
            path = f"{BASE}/{created.json()['session_id']}"
            async with stream(app, f"{path}/events") as updates:
                first = await updates.event()
                assert isinstance(first, SnapshotEvent) and first.snapshot.history == ()
                accepted = await asyncio.wait_for(client.post(f"{path}/turns", json={"prompt": "Present."}), 5)
                assert accepted.status_code == 202 and accepted.json() == {"kind": "accepted"}
                await asyncio.wait_for(continuing.wait(), 5)
                busy = await client.post(f"{path}/turns", json={"prompt": "Rejected."})
                assert busy.status_code == 409 and busy.json() == {"kind": "busy"}
                active = await updates.until(lambda snapshot: any(
                    isinstance(part, AcceptedArtifact) for turn in turns(snapshot) for part in turn.parts
                ))
                parts = turns(active)[-1].parts
                assert [part.part_kind for part in parts] == ["text", "tool-call", "artifact"]
                assert isinstance(parts[1], ToolActivity) and parts[1].tool_call_id == "artifact"
                assert turns(active)[-1].lifecycle.status == "running"
                assert "SECRET" not in active.model_dump_json()
                release.set()
                final = await updates.until(lambda snapshot: turns(snapshot)[-1].lifecycle.status == "failed")
                assert "SECRET" not in final.model_dump_json()
                read = await client.get(path)
                assert read.status_code == 200 and PresentedSession.model_validate_json(read.content) == final
                assert (await client.post(f"{path}/turns", json={"prompt": "Follow up."})).status_code == 202
                followup = await updates.until(lambda snapshot: len(turns(snapshot)) == 2 and turns(snapshot)[-1].lifecycle.status == "failed")
                assert turns(followup)[0] == turns(final)[0]

    asyncio.run(exercise())


@pytest.mark.parametrize("identity", [None, "", "alice", "test:two words", "test:alice:other"])
def test_identity_and_request_validation(identity: str | None) -> None:
    async def exercise() -> None:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise AssertionError("Validation must not execute the agent")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(application(runner)), base_url="http://test") as client:
            headers = {} if identity is None else {"X-Application-User": identity}
            for method, path, body in (("POST", BASE, {}), ("GET", f"{BASE}/missing", None),
                                       ("POST", f"{BASE}/missing/turns", {"prompt": "Hello"}),
                                       ("GET", f"{BASE}/missing/events", None)):
                assert (await client.request(method, path, json=body, headers=headers)).status_code == 422
            for body in ({"prompt": ""}, {"prompt": "  "}, {"prompt": 42}, {"prompt": "x" * 16001}, {"prompt": "Hi", "other": True}):
                assert (await client.post(f"{BASE}/missing/turns", json=body, headers=IDENTITY)).status_code == 422
            assert (await client.post(BASE, json={"extra": True}, headers=IDENTITY)).status_code == 422

    asyncio.run(exercise())


def test_owner_expiry_configuration_and_shutdown_errors_before_stream_headers() -> None:
    async def exercise() -> None:
        now = datetime(2026, 10, 21, tzinfo=UTC)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent, clock=lambda: now)
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(application(runner)), base_url="http://test", headers=IDENTITY) as client:
            created = await client.post(BASE, json={})
            path = f"{BASE}/{created.json()['session_id']}"
            for method, suffix, body in (("GET", "", None), ("GET", "/events", None), ("POST", "/turns", {"prompt": "Hi"})):
                denied = await client.request(method, path + suffix, json=body, headers={"X-Application-User": "test:bob"})
                missing = await client.request(method, f"{BASE}/missing" + suffix, json=body)
                assert denied.status_code == missing.status_code == 404
                assert denied.json() == missing.json() == {"kind": "unknown"}
            assert (await client.post(BASE.replace("/test/", "/other/"), json={})).status_code == 404
            assert (await client.post(BASE.replace("/test/", "/unavailable/"), json={})).status_code == 503
            await runner.close()
            assert (await client.post(BASE, json={})).status_code == 503
            assert (await client.post(f"{path}/turns", json={"prompt": "Hi"})).status_code == 503
            assert (await client.get(path)).status_code == 200
            closed = await client.get(f"{path}/events")
            assert closed.status_code == 200 and closed.text.count("data:") == 1
            now += timedelta(minutes=90)
            assert (await client.get(path)).status_code == 404
            assert (await client.get(f"{path}/events")).status_code == 404

    asyncio.run(exercise())


def test_stream_disconnect_releases_capacity_without_cancelling_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        monkeypatch.setattr("app.agentic.sessions.MAX_OBSERVERS_PER_SESSION", 1)
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        app = application(runner)
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers=IDENTITY) as client:
            created = await client.post(BASE, json={})
            path = f"{BASE}/{created.json()['session_id']}"
            async with stream(app, f"{path}/events") as first:
                await first.event()
                excess = await client.get(f"{path}/events")
                assert excess.status_code == 429 and excess.json() == {"kind": "observation_limit"}
                assert (await client.get(f"{path}/events", headers={"X-Application-User": "test:bob"})).status_code == 404
                await client.post(f"{path}/turns", json={"prompt": "Work."})
                await asyncio.wait_for(started.wait(), 5)
            async with stream(app, f"{path}/events") as replacement:
                first_event = await replacement.event()
                assert isinstance(first_event, SnapshotEvent)
                assert turns(first_event.snapshot)[-1].lifecycle.status == "running"
                release.set()
                final = await replacement.until(lambda snapshot: turns(snapshot)[-1].lifecycle.status == "completed")
                assert turns(final)[-1].parts[-1].part_kind == "text"
                await runner.close()
                assert (await replacement.next_message())["more_body"] is False

    asyncio.run(exercise())


def test_openapi_advertises_native_snapshots_and_typed_sse() -> None:
    app = FastAPI()
    app.include_router(create_session_router(lambda: {}))
    schema = app.openapi()
    responses = schema["paths"][BASE.replace("test", "{configuration}") + "/{session_id}/events"]["get"]["responses"]
    event_schema = responses["200"]["content"]["text/event-stream"]["schema"]
    assert event_schema["type"] == "object" and "$ref" in event_schema
    assert "SnapshotEvent" in schema["components"]["schemas"]
    assert "ObservationErrorEvent" in schema["components"]["schemas"]
    assert "PresentedSession" in schema["components"]["schemas"]
    json.dumps(schema, allow_nan=False)


@pytest.mark.parametrize("failure,reason", [
    (ObservationOverflowError, "observation_overflow"),
    (SessionNotFoundError, "unknown"),
    (RuntimeError, "internal_error"),
])
def test_errors_after_headers_are_typed_and_close_observation(
    failure: type[Exception], reason: Literal["observation_overflow", "unknown", "internal_error"], caplog: pytest.LogCaptureFixture,
) -> None:
    async def exercise() -> None:
        closed = asyncio.Event()

        class FailingRunner(AgentTurnRunner):
            async def observe_session(self, session_id: str, *, owner: str) -> AsyncGenerator[PresentedSession, None]:
                try:
                    yield self.read_session(session_id, owner=owner)
                    raise failure("SECRET_OBSERVATION_ERROR")
                finally:
                    closed.set()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = FailingRunner(agent)
        app = application(runner)
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test", headers=IDENTITY) as client:
            created = await client.post(BASE, json={})
            response = await client.get(f"{BASE}/{created.json()['session_id']}/events")
            assert response.status_code == 200
            frames = [EVENT_ADAPTER.validate_json(frame[6:]) for frame in response.text.strip().split("\n\n")]
            assert len(frames) == 2 and isinstance(frames[0], SnapshotEvent)
            assert frames[1] == ObservationErrorEvent(reason=reason)
            assert closed.is_set() and "SECRET" not in response.text

    asyncio.run(exercise())
    assert "SECRET" not in caplog.text


def test_invalid_initialization_rejects_context_and_duplicate_capabilities() -> None:
    async def exercise() -> None:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise AssertionError("Invalid initialization must not execute the agent")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        capability = {"type": "example", "description": "Display.", "payloadSchema": {"type": "object"}}
        async with agent, runner, httpx.AsyncClient(transport=httpx.ASGITransport(application(runner)), base_url="http://test", headers=IDENTITY) as client:
            for body in ({"initial_context": {"text": "x" * 64000}}, {"artifact_capabilities": [capability, capability]}):
                response = await client.post(BASE, json=body)
                assert response.status_code == 400 and response.json() == {"kind": "invalid_input"}
            assert (await client.post(BASE, json={"artifact_capabilities": [{**capability, "payloadSchema": {"$ref": "https://example.com/schema"}}]})).status_code == 422
            assert (await client.post(BASE, json={})).status_code == 201

    asyncio.run(exercise())


@pytest.mark.parametrize("failed_message", ["http.response.start", "http.response.body"])
def test_failed_socket_send_releases_preacquired_subscription(
    failed_message: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        class BrokenStream(Stream):
            async def send(self, message: Message) -> None:
                if message["type"] == failed_message:
                    raise OSError("Connection closed")
                await super().send(message)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done.")])

        monkeypatch.setattr("app.agentic.sessions.MAX_OBSERVERS_PER_SESSION", 1)
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        app = application(runner)
        async with agent, runner:
            session = runner.create_session(owner="test:alice")
            path = f"{BASE}/{session.session_id}/events"
            broken = BrokenStream(app, path)
            broken.spec_version = "2.4"
            with pytest.raises(ClientDisconnect):
                await asyncio.wait_for(broken.run(), 5)
            async with stream(app, path) as replacement:
                assert isinstance(await replacement.event(), SnapshotEvent)

    asyncio.run(exercise())
