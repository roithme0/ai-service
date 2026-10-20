import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic_ai import Tool, models
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agentic.mcp import create_mcp_toolset
from app.agentic.turns import create_turn_agent, execute_turn


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@asynccontextmanager
async def connected_toolset(
    server: MCPServer,
    *,
    response_hook: Callable[[httpx2.Response], Awaitable[None]] | None = None,
) -> AsyncIterator[tuple[MCPToolset[None], httpx2.AsyncClient]]:
    app = server.streamable_http_app(
        streamable_http_path="/mcp/", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
    )
    async with app.router.lifespan_context(app), httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        event_hooks={"response": [response_hook]} if response_hook else {},
    ) as http:
        yield create_mcp_toolset("http://localhost/mcp/", id="domain", http_client=http), http


def test_mcp_discovery_instructions_execution_history_and_cleanup() -> None:
    server = MCPServer("Domain", instructions="Use domain tools to retrieve values.")
    calls: list[str] = []
    requests = 0

    @server.tool()
    def lookup_value(label: str) -> dict[str, int]:
        """Retrieve a domain value by label."""
        calls.append(label)
        return {"value": 42}

    def local_status() -> str:
        """Read the local status."""
        return "ready"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert info.instructions is not None
        assert "Help the user." in info.instructions
        assert "Use domain tools to retrieve values." in info.instructions
        tools = {tool.name: tool for tool in info.function_tools}
        assert set(tools) == {"lookup_value", "local_status"}
        assert tools["lookup_value"].description == "Retrieve a domain value by label."
        assert tools["lookup_value"].parameters_json_schema["required"] == ["label"]
        if requests == 1:
            return ModelResponse(parts=[ToolCallPart("lookup_value", {"label": "sample"}, "call-1")])
        results = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        assert len(results) == 1
        assert results[0].tool_call_id == "call-1"
        assert results[0].content == {"value": 42}
        assert results[0].outcome == "success"
        return ModelResponse(parts=[TextPart("The value is 42.")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, http):
            agent = create_turn_agent(
                FunctionModel(respond), instructions="Help the user.",
                tools=[Tool(local_status)], toolsets=[toolset],
            )
            async with agent:
                assert toolset.client.is_connected()
                first = await execute_turn(agent, "Find the sample value.")
                history = ModelMessagesTypeAdapter.validate_json(first.all_messages_json())
                second = await execute_turn(agent, "Repeat that value.", message_history=history)
                assert first.output == second.output == "The value is 42."
                assert second.usage.tool_calls == 0
            assert not toolset.client.is_connected()
            assert not http.is_closed
        assert http.is_closed

    asyncio.run(exercise())
    assert calls == ["sample"]
    assert requests == 3


def test_mcp_explicit_failure_reaches_model_without_reexecution() -> None:
    server = MCPServer("Domain")
    calls = 0

    @server.tool()
    def lookup_value() -> str:
        """Retrieve a domain value."""
        nonlocal calls
        calls += 1
        raise ToolError("Value unavailable")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls == 0:
            return ModelResponse(parts=[ToolCallPart("lookup_value", {}, "call-1")])
        result = messages[-1].parts[0]
        assert isinstance(result, ToolReturnPart)
        assert result.outcome == "failed"
        assert "Value unavailable" in str(result.content)
        return ModelResponse(parts=[TextPart("The lookup failed.")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, _):
            agent = create_turn_agent(FunctionModel(respond), instructions="Help.", toolsets=[toolset])
            async with agent:
                result = await execute_turn(agent, "Find the value.")
                assert result.output == "The lookup failed."
            assert not toolset.client.is_connected()

    asyncio.run(exercise())
    assert calls == 1


def test_lost_mcp_response_does_not_replay_completed_operation() -> None:
    server = MCPServer("Domain")
    calls = 0
    requests = 0

    @server.tool()
    def update_value() -> str:
        """Update a domain value."""
        nonlocal calls
        calls += 1
        return "Updated"

    async def lose_tool_response(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            payload = json.loads(response.request.content)
            if payload.get("method") == "tools/call":
                assert calls == 1
                await response.aclose()
                raise httpx2.ReadError("Response lost after execution", request=response.request)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[ToolCallPart("update_value", {}, "call-1")])

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=lose_tool_response) as (toolset, _):
            agent = create_turn_agent(FunctionModel(respond), instructions="Help.", toolsets=[toolset])
            with pytest.raises(httpx2.ReadError, match="Response lost after execution"):
                async with agent:
                    with pytest.raises(httpx2.ReadError, match="Response lost after execution"):
                        await execute_turn(agent, "Update the value.")
            assert not toolset.client.is_connected()

    asyncio.run(exercise())
    assert calls == 1
    assert requests == 1


def test_mcp_connection_failure_cleans_up_without_model_request() -> None:
    attempts = 0

    def unavailable(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectError("MCP unavailable", request=request)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        pytest.fail("Model must not run when the MCP connection cannot be opened.")

    async def exercise() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(unavailable)) as http:
            toolset = create_mcp_toolset("http://localhost/mcp/", id="domain", http_client=http)
            agent = create_turn_agent(FunctionModel(respond), instructions="Help.", toolsets=[toolset])
            with pytest.raises(RuntimeError, match="Client failed to connect: MCP unavailable") as failure:
                async with agent:
                    await execute_turn(agent, "Find the value.")
            assert isinstance(failure.value.__cause__, httpx2.ConnectError)
            assert not toolset.client.is_connected()
            assert not http.is_closed
        assert http.is_closed

    asyncio.run(exercise())
    assert attempts == 1
