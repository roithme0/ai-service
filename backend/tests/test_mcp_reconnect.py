import asyncio

import pytest
from mcp import Client
from mcp.client.session import ClientSession
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT, CallToolResult

from app.agents.enums.runtime import RuntimeStatus
from app.agents.models.tools import ToolInvocation
from app.agents.runtime import AgentRuntime
from app.mcp.connection import MCPConnectionConfig
from runtime_wait import wait_for_status


@pytest.mark.parametrize("during_poll", [False, True])
def test_connection_loss_rebuilds_sdk_contexts_without_replaying_calls(
    monkeypatch: pytest.MonkeyPatch, during_poll: bool,
) -> None:
    async def exercise() -> None:
        server = MCPServer("Recovery", instructions="Original guidance")
        mutations: list[str] = []
        clients: list[Client] = []
        retrying = asyncio.Event()
        allow_reconnect = False
        agent = object()

        @server.tool()
        def mutate() -> str:
            mutations.append("mutation")
            return "done"

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            if len(clients) >= 2 and not allow_reconnect:
                retrying.set()
                raise ConnectionError("still offline")
            client = Client(server, read_timeout_seconds=read_timeout_seconds)
            clients.append(client)
            return client

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
        monkeypatch.setattr("app.mcp.config.INITIAL_RETRY_SECONDS", 0.001)
        monkeypatch.setattr("app.mcp.config.CATALOGUE_REFRESH_SECONDS", 0.001 if during_poll else 300)
        runtime = AgentRuntime("test", agent, mcp_servers=(
            MCPConnectionConfig("first", "http://localhost/mcp"),
            MCPConnectionConfig("second", "http://localhost/mcp"),
        ))
        connections = runtime.mcp_connections
        original_call = Client.call_tool
        original_discover = ClientSession.send_discover
        call_count = 0

        async def lost_call(self: Client, name: str, arguments: dict[str, object]) -> CallToolResult:
            nonlocal call_count
            call_count += 1
            await original_call(self, name, arguments)
            raise MCPError(CONNECTION_CLOSED, "response lost after mutation")

        async def lost_discover(self: ClientSession, version: str) -> dict[str, object]:
            raise MCPError(CONNECTION_CLOSED, "session expired")

        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            if during_poll:
                monkeypatch.setattr(ClientSession, "send_discover", lost_discover)
                await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            else:
                registered = runtime.mcp_tools.registered_tools()[0]
                monkeypatch.setattr(Client, "call_tool", lost_call)
                result = await registered.execute(ToolInvocation(registered.name, "{}"))
                assert result.failed and "mcp_call_failed" in str(result.output)
                assert runtime.status == RuntimeStatus.UNAVAILABLE
                assert mutations == ["mutation"] and call_count == 1
            assert all(connection.tools == () and connection.instructions is None for connection in connections)
            assert runtime.issue is not None and runtime.issue.kind == "connection"
            assert runtime.agent is agent
            await asyncio.wait_for(retrying.wait(), 2)
            with pytest.raises((RuntimeError, MCPError)):
                await original_call(clients[0], "mutate", {})
            monkeypatch.setattr(Client, "call_tool", original_call)
            monkeypatch.setattr(ClientSession, "send_discover", original_discover)
            server._lowlevel_server.instructions = "Recovered guidance"
            allow_reconnect = True
            await wait_for_status(runtime, RuntimeStatus.READY)
            assert len(clients) == 4 and runtime.agent is agent
            assert all(connection.instructions == "Recovered guidance" for connection in connections)
            assert mutations == ([] if during_poll else ["mutation"])
            assert all(connection.tools[0].name == "mutate" for connection in connections)
        finally:
            await asyncio.wait_for(runtime.close(), 2)
        assert runtime.status == RuntimeStatus.CLOSED

    asyncio.run(exercise())


def test_late_failure_from_replaced_client_does_not_break_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        server = MCPServer("Concurrent failures")
        clients: list[Client] = []
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        @server.tool()
        def hello() -> str:
            return "hello"

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            client = Client(server, read_timeout_seconds=read_timeout_seconds)
            clients.append(client)
            return client

        async def failed_call(self: Client, name: str, arguments: dict[str, object]) -> CallToolResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            raise ConnectionError("old transport failed")

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
        monkeypatch.setattr("app.mcp.config.INITIAL_RETRY_SECONDS", 0.001)
        runtime = AgentRuntime("test", object(), mcp_servers=(MCPConnectionConfig("server", "http://localhost/mcp"),))
        await runtime.start()
        await wait_for_status(runtime, RuntimeStatus.READY)
        registered = runtime.mcp_tools.registered_tools()[0]
        monkeypatch.setattr(Client, "call_tool", failed_call)
        first = asyncio.create_task(registered.execute(ToolInvocation(registered.name, "{}")))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert (await registered.execute(ToolInvocation(registered.name, "{}"))).failed
            assert runtime.status == RuntimeStatus.UNAVAILABLE
            await wait_for_status(runtime, RuntimeStatus.READY)
            assert len(clients) == 2
            release.set()
            assert (await first).failed
            assert runtime.status == RuntimeStatus.READY and runtime.issue is None
            assert calls == 2 and len(clients) == 2
        finally:
            release.set()
            await first
            await runtime.close()

    asyncio.run(exercise())


def test_shutdown_interrupts_reconnection_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        server = MCPServer("Shutdown")
        attempts = 0

        @server.tool()
        def hello() -> str:
            return "hello"

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            nonlocal attempts
            attempts += 1
            return Client(server, read_timeout_seconds=read_timeout_seconds)

        async def failed_call(self: Client, name: str, arguments: dict[str, object]) -> CallToolResult:
            raise ConnectionError("offline")

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
        runtime = AgentRuntime("test", object(), mcp_servers=(MCPConnectionConfig("server", "http://localhost/mcp"),))
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            monkeypatch.setattr(Client, "call_tool", failed_call)
            registered = runtime.mcp_tools.registered_tools()[0]
            assert (await registered.execute(ToolInvocation(registered.name, "{}"))).failed
            assert runtime.status == RuntimeStatus.UNAVAILABLE
        finally:
            await asyncio.wait_for(runtime.close(), 2)
        assert runtime.status == RuntimeStatus.CLOSED and attempts == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [TimeoutError("slow"), MCPError(REQUEST_TIMEOUT, "slow"),
                                    MCPError(-32602, "invalid arguments")])
def test_tool_errors_and_timeouts_do_not_reconnect(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    async def exercise() -> None:
        server = MCPServer("Errors")
        clients: list[Client] = []

        @server.tool()
        def hello() -> str:
            return "hello"

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            client = Client(server, read_timeout_seconds=read_timeout_seconds)
            clients.append(client)
            return client

        async def failed_call(self: Client, name: str, arguments: dict[str, object]) -> CallToolResult:
            raise failure

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
        runtime = AgentRuntime("test", object(), mcp_servers=(MCPConnectionConfig("server", "http://localhost/mcp"),))
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.READY)
            monkeypatch.setattr(Client, "call_tool", failed_call)
            registered = runtime.mcp_tools.registered_tools()[0]
            assert (await registered.execute(ToolInvocation(registered.name, "{}"))).failed
            assert runtime.status == RuntimeStatus.READY and runtime.issue is None
            assert len(clients) == 1 and runtime.mcp_tools.registered_tools()
        finally:
            await runtime.close()

    asyncio.run(exercise())
