import asyncio
import json
from datetime import timedelta
from typing import Never

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.agents.openai_agentic_generation import OpenAIAgenticGenerator
from app.sessions.models.conversation import ConversationSessionSettings
from app.sessions.session_store import ConversationSessionStore
from app.sessions.models.history import ExecutionReportRecord, HostedToolRecord, ToolResultRecord
from app.agents.history_projection import model_input
from app.sessions.http import AgentTransport, _context_issue, get_agent_registry, router
from app.sessions.model_sessions import create_model_agent
from app.sessions.model_turn_execution import ModelTurnStrategy
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.models.tools import LocalToolSource
from app.sessions.models.execution import ToolExecution
from app.agents.models.web_search import WebSearchConfig
from reserved_turn import execute_reserved_turn
from test_openai_agentic_generation import EventStream, message, response_events


def search(identity: str, status: str = "completed", action: str = "search") -> dict[str, object]:
    return {"id": identity, "type": "web_search_call", "status": status,
            "action": {"type": action, "query": "fresh information"} if action == "search" else
            {"type": action, "url": "https://example.com", "pattern": "details"}}


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_openai_search_terminal_items_replay_and_request_allowance(status: str) -> None:
    requests: list[dict[str, object]] = []
    item = search("ws_1", status)

    def respond(request: httpx.Request) -> httpx.Response:
        payload: object = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=EventStream(response_events([item, message("Answer")])))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                generator = OpenAIAgenticGenerator("existing-model", client)
                result = await generator.generate(AgenticGenerationRequest((), "Instructions", ({"type": "web_search"},),
                                                                           max_hosted_tool_calls=3))
                assert result.output_items[0] == item
                assert result.tool_calls == ()
                await generator.generate(AgenticGenerationRequest(result.output_items, "Instructions", ()))
    asyncio.run(run())
    assert requests[0]["max_tool_calls"] == 3
    assert "max_tool_calls" not in requests[1]
    assert requests[1]["input"][0] == item


def test_mixed_search_budget_replay_and_fresh_turns() -> None:
    requests: list[AgenticGenerationRequest] = []
    invocations: list[str] = []
    outputs = [
        (search("ws_1"), search("ws_2", action="open_page")),
        (search("ws_3", action="find_in_page"), {"type": "function_call", "call_id": "local", "name": "sample", "arguments": "{}"}),
        (message("Finished"),), (message("Next"),),
    ]

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            items = outputs[len(requests) - 1]
            calls = (AgenticToolCall("local", "sample", "{}"),) if len(requests) == 2 else ()
            return AgenticGenerationResponse(items, calls, None)

    def execute(call: ToolInvocation) -> ToolExecution[Never]:
        invocations.append(call.arguments)
        return ToolExecution("Local result")

    async def run() -> None:
        store = ConversationSessionStore[str, Never](timedelta(minutes=90))
        strategy = ModelTurnStrategy(store, Generator(), lambda context: context,
                                     (LocalToolSource((RegisteredTool("sample", {"type": "function", "name": "sample"}, execute),)),),
                                     web_search=WebSearchConfig(3))
        session = store.create("Context", ConversationSessionSettings(20), owner="test:user").session_id
        store.append_user_message(session, "Start")
        assert (await execute_reserved_turn(store, strategy, session)).kind == "completed"
        history = store.history(session)
        hosted = [record for record in history if isinstance(record, HostedToolRecord)]
        assert len(hosted) == 3 and len({record.execution_id for record in hosted}) == 3
        assert len([record for record in history if isinstance(record, ToolResultRecord)]) == 1
        assert not any(isinstance(record, ExecutionReportRecord) for record in history)
        assert [item for item in model_input(history) if item.get("type") == "web_search_call"] == list(outputs[0]) + [outputs[1][0]]
        store.append_user_message(session, "Next")
        assert (await execute_reserved_turn(store, strategy, session)).kind == "completed"
    asyncio.run(run())
    assert invocations == ["{}"]
    assert [request.max_hosted_tool_calls for request in requests] == [3, 1, None, 3]
    assert [any(tool.get("type") == "web_search" for tool in request.tools) for request in requests] == [True, True, False, True]
    assert requests[2].input_items[-1] == {"type": "function_call_output", "call_id": "local", "output": "Local result"}
    assert outputs[0][0] in requests[3].input_items


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_search_survives_later_provider_failure_in_reads_and_sse(status: str) -> None:
    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            assert request.on_output_item is not None
            request.on_output_item(search("ws_1", status))
            raise RuntimeError("failure after search")

    agent = create_model_agent(Generator(), web_search=WebSearchConfig())
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_agent_registry] = lambda: {"test": AgentTransport(agent, lambda value: value, _context_issue)}
    with TestClient(application, headers={"X-Application-User": "test:user"}) as client:
        base = "/api/v1/agents/test/sessions"
        session = client.post(base, json={"input": {"context": {}}}).json()["session_id"]
        client.post(f"{base}/{session}/messages", json={"text": "Search"})
        turn = client.post(f"{base}/{session}/turns").json()["turn_id"]
        with client.stream("GET", f"{base}/{session}/turns/{turn}/events") as response:
            events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
        snapshot = client.get(f"{base}/{session}").json()
        row = next(item for item in snapshot["timeline"] if item["kind"] == "tool")
        assert row == {"kind": "tool", "turn_id": turn, "execution_id": row["execution_id"], "name": "web_search", "status": status}
        assert any(event["kind"] == "terminal" and event["outcome"] == "generation_failed" for event in events)
        visible = [item for event in events if event["kind"] == "snapshot" for item in event["snapshot"]["timeline"]]
        visible += [event["item"] for event in events if event["kind"] == "upsert"]
        assert row in visible


def test_concurrent_turn_budgets_are_isolated_and_search_is_opt_in() -> None:
    requests: list[AgenticGenerationRequest] = []
    entered = 0

    async def run() -> None:
        ready = asyncio.Event()

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                nonlocal entered
                requests.append(request)
                if request.max_hosted_tool_calls is not None:
                    entered += 1
                    if entered == 2:
                        ready.set()
                    await ready.wait()
                    assert request.on_output_item is not None
                    item = search(f"ws_{entered}_{len(requests)}")
                    request.on_output_item(item)
                    final = message("Answer")
                    request.on_output_item(final)
                    return AgenticGenerationResponse((item, final), (), "Answer")
                return AgenticGenerationResponse((message("Disabled"),), (), "Disabled")

        store = ConversationSessionStore[str, Never](timedelta(minutes=90))
        generator = Generator()
        enabled = ModelTurnStrategy(store, generator, lambda context: context, (), web_search=WebSearchConfig(1))
        disabled = ModelTurnStrategy(store, generator, lambda context: context, ())
        sessions = [store.create("Context", ConversationSessionSettings(20), owner="test:user").session_id for _ in range(3)]
        for session in sessions:
            store.append_user_message(session, "Run")
        results = await asyncio.gather(execute_reserved_turn(store, enabled, sessions[0]),
                                       execute_reserved_turn(store, enabled, sessions[1]),
                                       execute_reserved_turn(store, disabled, sessions[2]))
        assert all(result.kind == "completed" for result in results)
        assert [len([record for record in store.history(session) if isinstance(record, HostedToolRecord)])
                for session in sessions] == [1, 1, 0]

    asyncio.run(run())
    assert sorted(request.max_hosted_tool_calls or 0 for request in requests) == [0, 1, 1]
    assert all(({"type": "web_search"} in request.tools) == (request.max_hosted_tool_calls is not None) for request in requests)


@pytest.mark.parametrize("limit", [0, -1, True])
def test_invalid_search_budgets_are_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        WebSearchConfig(limit)


@pytest.mark.parametrize("status", ["in_progress", "searching"])
def test_incomplete_search_items_are_not_retained(status: str) -> None:
    recorded: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            stream=EventStream(response_events([search("ws_1", status)])),
        ))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises(ValueError, match="web search item is incomplete"):
                    await OpenAIAgenticGenerator("existing-model", client).generate(
                        AgenticGenerationRequest((), "Instructions", (), recorded.append))
    asyncio.run(run())
    assert recorded == []


def test_adapter_retains_search_before_later_stream_failure() -> None:
    async def run() -> None:
        stream = EventStream(response_events([search("ws_1")], "response.failed"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream,
        ))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                store = ConversationSessionStore[str, Never](timedelta(minutes=90))
                strategy = ModelTurnStrategy(store, OpenAIAgenticGenerator("existing-model", client),
                                             lambda context: context, (), web_search=WebSearchConfig())
                session = store.create("Context", ConversationSessionSettings(20), owner="test:user").session_id
                store.append_user_message(session, "Search")
                assert (await execute_reserved_turn(store, strategy, session)).kind == "generation_failed"
                history = store.history(session)
                records = [record for record in history if isinstance(record, HostedToolRecord)]
                assert len(records) == 1 and records[0].status == "completed"
                assert not any(isinstance(record, (ExecutionReportRecord, ToolResultRecord)) for record in history)
                assert model_input(history)[-1] == search("ws_1")
        assert stream.closed
    asyncio.run(run())
