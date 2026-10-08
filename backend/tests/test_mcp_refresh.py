import asyncio
from typing import Never

import httpx
import pytest
from mcp.types import CallToolResult, TextContent, Tool

from app.agents.enums.runtime import RuntimeStatus
from app.agents.model_agent import create_model_agent
from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.agents.runtime import AgentRuntime
from app.agents.tool_turns import run_tool_turn
from app.agents.wiring import ConfiguredAgents
from app.demo.agent import create_demo_agent
from app.main import app
from app.mcp.connection import MCPConnection, MCPDiscovery
from runtime_wait import wait_for_status
from test_model_session_http import FakeGenerator
from tool_turn_recorder import ToolTurnRecorder


def tool(name: str) -> Tool:
    return Tool(name=name, input_schema={"type": "object"})


class PollingConnection(MCPConnection):
    def __init__(self, name: str = "server", initial: tuple[Tool, ...] | None = None) -> None:
        super().__init__(name, "http://localhost/mcp/")
        self.tools = (tool("old"),) if initial is None else initial
        self.instructions = "Negotiated guidance"
        self.updates: asyncio.Queue[tuple[Tool, ...] | Exception] = asyncio.Queue()
        self.polling = asyncio.Event()
        self.settled = asyncio.Event()
        self.calls: list[str] = []
        self.starts = 0
        self.closed = False

    async def start(self) -> None:
        self.starts += 1

    async def discover(self) -> MCPDiscovery:
        self.polling.set()
        try:
            update = await self.updates.get()
            if isinstance(update, Exception):
                raise update
            return MCPDiscovery(update, "Refreshed guidance")
        finally:
            self.settled.set()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        self.calls.append(name)
        return CallToolResult(content=[TextContent(type="text", text="ok")])

    async def close(self) -> None:
        self.closed = True
        await super().close()


@pytest.mark.parametrize("failure", [(tool("invalid.name"),), (tool("duplicate"), tool("duplicate")),
                                    TimeoutError("offline")])
def test_failed_refresh_clears_catalogue_and_recovers(
    monkeypatch: pytest.MonkeyPatch, failure: tuple[Tool, ...] | Exception,
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        connection = PollingConnection()
        runtime = AgentRuntime("test", object(), mcp_connections=(connection,))
        source = runtime.mcp_tools
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            connection.updates.put_nowait(failure)
            await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            assert connection.tools == ()
            assert connection.instructions is None
            assert runtime.issue is not None and runtime.issue.connection == "server"
            assert source.registered_tools() == ()
            connection.updates.put_nowait(())
            await wait_for_status(runtime, RuntimeStatus.READY)
            assert connection.tools == () and runtime.issue is None
            assert runtime.mcp_tools is source and connection.starts == 1
            connection.updates.put_nowait((tool("new"),))
            async with asyncio.timeout(2):
                while not connection.tools:
                    await asyncio.sleep(0)
            assert [item.name for item in source.registered_tools()] == ["server__new"]
            assert "new -> server__new" in source.instructions
            assert connection.instructions == "Refreshed guidance"
        finally:
            await asyncio.wait_for(runtime.close(), 2)
        assert connection.closed and connection.settled.is_set()

    asyncio.run(exercise())


def test_invalid_initial_catalogue_recovers_by_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        connection = PollingConnection(initial=(tool("bad.name"),))
        runtime = AgentRuntime("test", object(), mcp_connections=(connection,))
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            assert connection.tools == ()
            assert connection.instructions is None
            connection.updates.put_nowait((tool("fixed"),))
            await wait_for_status(runtime, RuntimeStatus.READY)
            assert connection.starts == 1
        finally:
            await runtime.close()

    asyncio.run(exercise())


def test_cross_connection_collision_clears_only_affected_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        first = PollingConnection("a__b", (tool("c"),))
        second = PollingConnection("a", (tool("other"),))
        runtime = AgentRuntime("test", object(), mcp_connections=(first, second))
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            first.updates.put_nowait(first.tools)
            second.updates.put_nowait((tool("b__c"),))
            await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            assert first.tools == (tool("c"),) and second.tools == ()
            first.updates.put_nowait(first.tools)
            second.updates.put_nowait((tool("fixed"),))
            await wait_for_status(runtime, RuntimeStatus.READY)
        finally:
            await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("refresh_fails", [False, True])
def test_active_turn_keeps_snapshot_across_refresh(monkeypatch: pytest.MonkeyPatch, refresh_fails: bool) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        connection = PollingConnection()
        runtime = AgentRuntime("test", object(), mcp_connections=(connection,))
        entered = asyncio.Event()
        release = asyncio.Event()
        requests: list[AgenticGenerationRequest] = []

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) == 1:
                    entered.set()
                    await release.wait()
                    call = AgenticToolCall("call", "server__old", "{}")
                    return AgenticGenerationResponse(({
                        "type": "function_call", "call_id": call.call_id,
                        "name": call.name, "arguments": call.arguments,
                    },), (call,), None)
                return AgenticGenerationResponse(({
                    "type": "message", "role": "assistant", "phase": "final_answer", "content": "Done",
                },), (), "Done")

        recorder = ToolTurnRecorder[Never]()
        await runtime.start()
        await wait_for_status(runtime, RuntimeStatus.READY)
        turn = asyncio.create_task(run_tool_turn(
            Generator(), (), "Context", "Guidance", (runtime.mcp_tools,), 2, 1, 2,
            record_item=recorder.record_item, start_execution=recorder.start_execution,
            record_result=recorder.record_result,
        ))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if refresh_fails:
                connection.updates.put_nowait(TimeoutError("offline"))
                await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            else:
                connection.updates.put_nowait((tool("new"),))
                async with asyncio.timeout(2):
                    while connection.tools[0].name != "new":
                        await asyncio.sleep(0)
            release.set()
            assert (await turn).kind == "completed"
            assert connection.calls == ["old"]
            assert requests[0].tools == requests[1].tools
            assert requests[0].instructions == requests[1].instructions
            assert requests[0].tools[0]["name"] == "server__old"
            assert "Negotiated guidance" in requests[1].instructions
            assert "Refreshed guidance" not in requests[1].instructions
            if refresh_fails:
                connection.updates.put_nowait((tool("new"),))
                await wait_for_status(runtime, RuntimeStatus.READY)
            assert runtime.mcp_tools.registered_tools()[0].name == "server__new"
            next_recorder = ToolTurnRecorder[Never]()
            await run_tool_turn(
                Generator(), (), "Context", "Guidance", (runtime.mcp_tools,), 2, 1, 2,
                record_item=next_recorder.record_item, start_execution=next_recorder.start_execution,
                record_result=next_recorder.record_result,
            )
            assert requests[2].tools[0]["name"] == "server__new"
            assert "new -> server__new" in requests[2].instructions
            assert "Refreshed guidance" in requests[2].instructions
            assert "Negotiated guidance" not in requests[2].instructions
        finally:
            release.set()
            await turn
            await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("refresh_completes", [False, True])
def test_shutdown_settles_agent_before_interrupting_shared_connection(
    monkeypatch: pytest.MonkeyPatch, refresh_completes: bool,
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        entered = asyncio.Event()
        release = asyncio.Event()
        connection = PollingConnection()

        class Agent:
            async def close(self) -> None:
                entered.set()
                await release.wait()
                assert not connection.closed
                assert connection.settled.is_set() == refresh_completes
                await connection.call_tool("old", {})

        runtime = AgentRuntime("test", Agent(), mcp_connections=(connection,))
        await runtime.start()
        await asyncio.wait_for(connection.polling.wait(), 2)
        closing = asyncio.create_task(runtime.close())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert runtime.status == RuntimeStatus.CLOSING
            assert not connection.closed and not connection.settled.is_set()
            if refresh_completes:
                connection.updates.put_nowait((tool("new"),))
                await asyncio.wait_for(connection.settled.wait(), 2)
                await asyncio.sleep(0)
                assert not connection.closed
        finally:
            release.set()
            await asyncio.wait_for(closing, 2)
        assert connection.calls == ["old"]
        assert connection.closed and connection.settled.is_set()

    asyncio.run(exercise())


def test_unavailable_runtime_keeps_history_and_observation_but_blocks_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001)
        connection = PollingConnection()
        agent = create_model_agent(FakeGenerator(), tool_sources=())
        runtime = AgentRuntime("kochwiki", agent, mcp_connections=(connection,))
        agents = ConfiguredAgents(runtime, AgentRuntime("demo", create_demo_agent(delay_seconds=0)))
        monkeypatch.setattr("app.agents.http.get_configured_agents", lambda: agents)
        await agents.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://service",
                                         headers={"X-Application-User": "test:user"}) as http:
                base = "/api/v1/agents/kochwiki/sessions"
                created = await http.post(base, json={"input": {"context": {}}})
                assert created.status_code == 201
                session = f"{base}/{created.json()['session_id']}"
                assert (await http.post(f"{session}/messages", json={"text": "Hello"})).status_code == 201
                started = await http.post(f"{session}/turns")
                assert started.status_code == 202
                async with asyncio.timeout(2):
                    while not agent.turn_terminal(created.json()["session_id"], started.json()["turn_id"]):
                        await asyncio.sleep(0)
                before = (await http.get(session)).json()
                connection.updates.put_nowait(TimeoutError("offline"))
                await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
                assert (await http.get(session)).json() == before
                assert (await http.get(session, headers={"X-Application-User": "other:user"})).status_code == 404
                observed = await http.get(f"{session}/turns/{started.json()['turn_id']}/events")
                assert observed.status_code == 200 and '"kind":"terminal"' in observed.text
                for path, body in [(base, {}), (f"{session}/messages", {"text": "blocked"}),
                                   (f"{session}/turns", {})]:
                    response = await http.post(path, json=body)
                    assert response.status_code == 503
                    assert response.json()["kind"] == "agent_unavailable"
                assert (await http.get(session)).json() == before
                assert (await http.post("/api/v1/agents/demo/sessions", json={})).status_code == 201
                connection.updates.put_nowait((tool("fixed"),))
                await wait_for_status(runtime, RuntimeStatus.READY)
                assert (await http.post(f"{session}/messages", json={"text": "Again"})).status_code == 201
        finally:
            await agents.close()

    asyncio.run(exercise())
