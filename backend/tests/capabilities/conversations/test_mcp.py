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
from mcp.types import Resource as MCPResource
from pydantic_ai import Conversation, RunContext, Tool, models
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.mcp import EagerMCPResources, create_mcp_toolset
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
            assert observation.messages[-1].state == "interrupted"
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


def test_resources_are_loaded_once_per_turn_as_request_only_data() -> None:
    server = MCPServer("Domain")
    methods: list[str] = []
    reads: list[str] = []
    text = "first snapshot"
    requests = 0

    @server.resource("data://reference", name="Reference", mime_type="application/json")
    def reference() -> str:
        reads.append(text)
        return text

    @server.resource("data://binary", mime_type="image/png")
    def binary() -> bytes:
        return b"binary secret"

    @server.resource("data://template/{key}")
    def template(key: str) -> str:
        pytest.fail("Resource templates must not be expanded")

    @server.tool()
    def lookup() -> str:
        return "tool result"

    async def record(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            payload = json.loads(response.request.content)
            methods.append(payload["method"])

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        snapshots = [
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and part.content.startswith("MCP resource data")
        ]
        assert len(snapshots) == 1
        assert text in snapshots[0]
        assert "binary secret" not in snapshots[0]
        assert "data://binary" not in snapshots[0]
        assert "data://reference" in snapshots[0]
        assert '"name": "Reference"' in snapshots[0]
        assert reads == (
            ["first snapshot"]
            if requests < 3
            else ["first snapshot", "second snapshot"]
        )
        assert text not in (info.instructions or "")
        assert {tool.name for tool in info.function_tools} == {"lookup"}
        if requests == 1:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup-1")])
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        nonlocal text
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
                capabilities=[EagerMCPResources(factory)],
            )
            async with agent:
                first = await execute_turn(agent, "First")
                assert "first snapshot" not in first.all_messages_json().decode()
                text = "second snapshot"
                second = await execute_turn(
                    agent,
                    "Second",
                    conversation=Conversation(messages=first.all_messages()),
                )
                assert "second snapshot" not in second.all_messages_json().decode()
            assert all(not toolset.client.is_connected() for toolset in toolsets)
        assert methods.count("resources/list") == 2
        assert methods.count("resources/read") == 4
        assert "resources/templates/list" not in methods

    asyncio.run(exercise())


def test_mixed_resource_contents_skip_binary_and_preserve_all_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPServer("Domain")

    @server.resource("data://mixed", mime_type="application/graphql")
    def mixed() -> str:
        return "unused"

    async def read(uri: object, context: object) -> list[ReadResourceContents]:
        assert str(uri) == "data://mixed"
        return [
            ReadResourceContents(content="first", mime_type="application/xml"),
            ReadResourceContents(content=b"binary secret", mime_type="image/png"),
            ReadResourceContents(content="second", mime_type="text/plain"),
        ]

    monkeypatch.setattr(server, "read_resource", read)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = messages[-1].parts[-1]
        assert isinstance(prompt, UserPromptPart)
        assert isinstance(prompt.content, str)
        assert '"text": "first"' in prompt.content, str(messages)
        assert '"text": "second"' in prompt.content
        assert "binary secret" not in prompt.content
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[EagerMCPResources(lambda ctx: toolset)],
            )
            async with agent:
                await execute_turn(agent, "Read")

    asyncio.run(exercise())


def test_empty_resource_snapshot_is_discovered_once_across_model_steps() -> None:
    server = MCPServer("Domain")
    methods: list[str] = []
    requests = 0

    @server.tool()
    def lookup() -> str:
        return "done"

    async def record(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            methods.append(json.loads(response.request.content)["method"])

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert "MCP resource data" not in str(messages)
        if requests == 1:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup-1")])
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=record) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[EagerMCPResources(lambda ctx: toolset)],
            )
            async with agent:
                await execute_turn(agent, "Read")

    asyncio.run(exercise())
    assert methods.count("resources/list") == 1


def test_resources_serialize_as_user_data_in_openai_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPServer("Domain")
    requests: list[dict[str, object]] = []

    @server.resource("data://reference")
    def reference() -> str:
        return "resource body"

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.2",
                "status": "completed",
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "done", "annotations": []}
                        ],
                    }
                ],
            },
        )

    async def exercise() -> None:
        async with connected_toolset(server) as (toolset, _):
            async with httpx2.AsyncClient(
                transport=httpx2.MockTransport(respond)
            ) as http:
                monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
                model = OpenAIResponsesModel(
                    "gpt-5.2", provider=OpenAIProvider(api_key="test", http_client=http)
                )
                agent = create_turn_agent(
                    model,
                    instructions="Help.",
                    capabilities=[EagerMCPResources(lambda ctx: toolset)],
                )
                async with agent:
                    result = await execute_turn(agent, "Read")
                    assert result.output == "done"
                    assert "resource body" not in result.all_messages_json().decode()

    asyncio.run(exercise())
    assert len(requests) == 1
    inputs = requests[0]["input"]
    assert isinstance(inputs, list)
    resource_messages = [item for item in inputs if "resource body" in str(item)]
    assert len(resource_messages) == 1
    assert resource_messages[0]["role"] == "user"
    assert "resource body" not in str(requests[0].get("instructions"))


@pytest.mark.parametrize("characters", [64_000, 64_001])
def test_resource_content_limit_uses_aggregate_actual_text(
    characters: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = MCPServer("Domain")
    requests = 0

    @server.resource("data://one")
    def one() -> str:
        return "é" * 32_000

    @server.resource("data://two")
    def two() -> str:
        return "x" * (characters - 32_000)

    list_resources = server.list_resources

    async def reported_sizes() -> list[MCPResource]:
        resources = await list_resources()
        for resource in resources:
            resource.size = 0 if characters > 64_000 else 1_000_000
        return resources

    monkeypatch.setattr(server, "list_resources", reported_sizes)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[TextPart("done")])

    async def exercise() -> None:
        async with connected_toolset(server) as (_, http):
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
                capabilities=[EagerMCPResources(factory)],
            )
            async with agent:
                if characters > 64_000:
                    with pytest.raises(ValueError, match="64,000 characters"):
                        await execute_turn(agent, "Read")
                else:
                    await execute_turn(agent, "Read")
            assert all(not toolset.client.is_connected() for toolset in toolsets)

    asyncio.run(exercise())
    assert requests == (0 if characters > 64_000 else 1)


@pytest.mark.parametrize("method", ["resources/list", "resources/read"])
def test_resource_transport_failure_prevents_model_request(method: str) -> None:
    server = MCPServer("Domain")

    @server.resource("data://reference")
    def reference() -> str:
        return "reference"

    async def fail(response: httpx2.Response) -> None:
        if response.request.method == "POST":
            payload = json.loads(response.request.content)
            if payload.get("method") == method:
                await response.aclose()
                raise httpx2.ReadError("Resource unavailable", request=response.request)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        pytest.fail("Model must not run after resource failures")

    async def exercise() -> None:
        async with connected_toolset(server, response_hook=fail) as (toolset, _):
            agent = create_turn_agent(
                FunctionModel(respond),
                instructions="Help.",
                capabilities=[EagerMCPResources(lambda ctx: toolset)],
            )
            async with agent:
                with pytest.raises(httpx2.ReadError, match="Resource unavailable"):
                    await execute_turn(agent, "Read")
                assert not toolset.client.is_connected()

    asyncio.run(exercise())
