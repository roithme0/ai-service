import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic_ai import Conversation, RunContext, Tool, models
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.mcp import MCPToolset, Resource
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.mcp import MCPResources, create_mcp_toolset
from app.capabilities.conversations.observation import TurnObservation
from app.capabilities.conversations.turns import create_turn_agent, execute_turn


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
        streamable_http_path="/mcp/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            event_hooks={"response": [response_hook]} if response_hook else {},
        ) as http,
    ):
        yield create_mcp_toolset(
            "http://localhost/mcp/", id="domain", http_client=http
        ), http


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
            return ModelResponse(
                parts=[ToolCallPart("lookup_value", {"label": "sample"}, "call-1")]
            )
        results = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert len(results) == 1
        assert results[0].tool_call_id == "call-1"
        assert results[0].content == {"value": 42}
        assert results[0].outcome == "success"
        return ModelResponse(parts=[TextPart("The value is 42.")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, http):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help the user.",
                tools=[Tool(local_status)],
                toolsets=[toolset],
            )
            async with agent:
                assert toolset.client.is_connected()
                first = await execute_turn(agent, "Find the sample value.")
                history = ModelMessagesTypeAdapter.validate_json(
                    first.all_messages_json()
                )
                second = await execute_turn(
                    agent,
                    "Repeat that value.",
                    conversation=Conversation(messages=list(history)),
                )
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
            agent = create_turn_agent(
                FunctionModel(respond), instructions="Help.", toolsets=[toolset]
            )
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
                raise httpx2.ReadError(
                    "Response lost after execution", request=response.request
                )

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[ToolCallPart("update_value", {}, "call-1")])

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=lose_tool_response) as (
            toolset,
            _,
        ):
            agent = create_turn_agent(
                FunctionModel(respond), instructions="Help.", toolsets=[toolset]
            )
            observation = TurnObservation()
            with pytest.raises(httpx2.ReadError, match="Response lost after execution"):
                async with agent:
                    with pytest.raises(
                        httpx2.ReadError, match="Response lost after execution"
                    ):
                        await execute_turn(
                            agent, "Update the value.", observation=observation
                        )
            assert not toolset.client.is_connected()
            assert [call.tool_call_id for call in observation.started_tool_calls] == [
                "call-1"
            ]
            assert observation.messages[-1].state == "interrupted", str(
                observation.messages
            )
            assert not any(
                isinstance(part, ToolReturnPart)
                for msg in observation.messages
                for part in msg.parts
            )

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
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(unavailable)
        ) as http:
            toolset = create_mcp_toolset(
                "http://localhost/mcp/", id="domain", http_client=http
            )
            agent = create_turn_agent(
                FunctionModel(respond), instructions="Help.", toolsets=[toolset]
            )
            with pytest.raises(
                RuntimeError, match="Client failed to connect: MCP unavailable"
            ) as failure:
                async with agent:
                    await execute_turn(agent, "Find the value.")
            assert isinstance(failure.value.__cause__, httpx2.ConnectError)
            assert not toolset.client.is_connected()
            assert not http.is_closed
        assert http.is_closed

    asyncio.run(exercise())
    assert attempts == 1


def test_resource_index_and_native_history_across_turns() -> None:
    server = MCPServer("Domain")
    methods: list[str] = []
    reads: list[str] = []
    text = "x" * 80_000
    requests = 0

    @server.resource("data://reference", name="Reference", description="Useful data")
    def reference() -> str:
        reads.append(text)
        return text

    @server.resource("data://unused", name="Unused")
    def unused() -> str:
        pytest.fail("Unrequested resource must not be read")

    @server.resource("data://template/{key}")
    def template(key: str) -> str:
        pytest.fail("Templates must not be expanded")

    async def record(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            methods.append(json.loads(response.request.content)["method"])

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        index = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and part.content.startswith("MCP resource index")
        ]
        assert len(index) == 1
        assert "data://reference" in index[0] and "Useful data" in index[0]
        assert '"name": "Reference"' in index[0]
        assert '"name": "Unused"' in index[0] and '"description": ""' in index[0]
        assert text not in index[0]
        assert "data://template" not in index[0]
        assert "get_mcp_resource" in {tool.name for tool in info.function_tools}
        if requests == 1:
            assert not reads
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_mcp_resource", {"uri": "data://reference"}, "read-1"
                    )
                ]
            )
        results = [
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert results[0].content == [text]
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=record) as (_, http):
            toolsets: list[MCPToolset[None]] = []

            def factory(ctx: RunContext[None]) -> MCPToolset[None]:
                toolset = create_mcp_toolset(
                    "http://localhost/mcp/", id="domain", http_client=http
                )
                toolsets.append(toolset)
                return toolset

            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[MCPResources(factory)],
            )
            async with agent:
                first = await execute_turn(agent, "First")
                assert text in first.all_messages_json().decode()
                assert "MCP resource index" not in first.all_messages_json().decode()
                await execute_turn(
                    agent,
                    "Second",
                    conversation=Conversation(messages=first.all_messages()),
                )
            assert all(not toolset.client.is_connected() for toolset in toolsets)
        assert methods.count("resources/list") == 2
        assert methods.count("resources/read") == 1
        assert "resources/templates/list" not in methods

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["unknown", "binary", "mixed", "server_error"])
def test_resource_read_errors_are_native_failed_tool_results(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = MCPServer("Domain")
    reads: list[str] = []

    @server.resource("data://reference")
    def reference() -> str:
        return "unused"

    async def read(uri: object, context: object) -> list[ReadResourceContents]:
        reads.append(str(uri))
        if kind == "server_error":
            raise ValueError("unavailable")
        if kind == "binary":
            return [ReadResourceContents(content=b"secret", mime_type="image/png")]
        return [
            ReadResourceContents(content="text", mime_type="application/json"),
            ReadResourceContents(content=b"secret", mime_type="image/png"),
        ]

    monkeypatch.setattr(server, "read_resource", read)
    requests = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        if requests == 1:
            uri = (
                "https://example.invalid/unknown"
                if kind == "unknown"
                else "data://reference"
            )
            return ModelResponse(
                parts=[ToolCallPart("get_mcp_resource", {"uri": uri}, "read")]
            )
        result = next(
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        )
        assert result.outcome == "failed"
        assert "secret" not in str(result.content)
        assert (
            "not in the current index"
            if kind == "unknown"
            else (
                "read failed"
                if kind == "server_error"
                else "binary content is unsupported"
            )
        ) in str(result.content)
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[MCPResources(lambda ctx: toolset)],
            )
            async with agent:
                await execute_turn(agent, "Read")
            assert not toolset.client.is_connected()
        assert reads == ([] if kind == "unknown" else ["data://reference"])

    asyncio.run(exercise())


def test_multipart_text_preserves_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    server = MCPServer("Domain")

    @server.resource("data://parts")
    def parts() -> str:
        return "unused"

    async def read(uri: object, context: object) -> list[ReadResourceContents]:
        return [
            ReadResourceContents(content="<a />", mime_type="application/xml"),
            ReadResourceContents(content="{}", mime_type="application/json"),
        ]

    monkeypatch.setattr(server, "read_resource", read)
    calls = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart("get_mcp_resource", {"uri": "data://parts"}, "read")
                ]
            )
        result = next(
            part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        )
        assert result.content == ["<a />", "{}"]
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[MCPResources(lambda ctx: toolset)],
            )
            async with agent:
                await execute_turn(agent, "Read")

    asyncio.run(exercise())


def test_empty_catalog_discovered_once(monkeypatch: pytest.MonkeyPatch) -> None:
    server = MCPServer("Domain")
    methods: list[str] = []
    calls = 0

    @server.tool()
    def lookup() -> str:
        return "done"

    async def record(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            methods.append(json.loads(response.request.content)["method"])

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        assert "MCP resource index" not in str(messages)
        return (
            ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup")])
            if calls == 1
            else ModelResponse(parts=[TextPart("done")])
        )

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=record) as (toolset, _):
            discoveries = 0
            original_list = toolset.list_resources

            async def discover() -> list[Resource]:
                nonlocal discoveries
                discoveries += 1
                return await original_list()

            monkeypatch.setattr(toolset, "list_resources", discover)
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[MCPResources(lambda ctx: toolset)],
            )
            async with agent:
                await execute_turn(agent, "Read")
            assert discoveries == 1
        assert methods.count("resources/list") <= 1

    asyncio.run(exercise())


@pytest.mark.parametrize("method", ["resources/list", "resources/read"])
def test_resource_transport_failure_closes_session(method: str) -> None:
    server = MCPServer("Domain")
    calls = 0

    @server.resource("data://reference")
    def reference() -> str:
        return "content"

    async def fail(response: httpx2.Response) -> None:
        if (
            response.request.method == "POST"
            and json.loads(response.request.content).get("method") == method
        ):
            await response.aclose()
            raise httpx2.ReadError("Resource unavailable", request=response.request)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        assert method == "resources/read"
        assert calls == 1, str(messages)
        return ModelResponse(
            parts=[
                ToolCallPart("get_mcp_resource", {"uri": "data://reference"}, "read")
            ]
        )

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=fail) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[MCPResources(lambda ctx: toolset)],
            )
            observation = TurnObservation()
            with pytest.raises(httpx2.ReadError, match="Resource unavailable"):
                async with agent:
                    await execute_turn(agent, "Read", observation=observation)
            assert not toolset.client.is_connected()
            if method == "resources/read":
                assert [
                    call.tool_call_id for call in observation.started_tool_calls
                ] == ["read"]
                assert observation.messages[-1].state == "interrupted", str(
                    observation.messages
                )
                assert not any(
                    isinstance(part, ToolReturnPart)
                    for msg in observation.messages
                    for part in msg.parts
                )
        assert calls == (0 if method == "resources/list" else 1)

    asyncio.run(exercise())
