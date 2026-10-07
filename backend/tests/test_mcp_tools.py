import asyncio
import json
from typing import Never

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from app.agents.runtime import AgentRuntime
from app.mcp.connection import MCPConnection
from app.mcp.tools import MCPToolset
from app.agents.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.tool_turns import run_tool_turn
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.tools import LocalToolSource, ToolRegistry
from app.sessions.models.execution import ToolExecution
from tool_turn_recorder import ToolTurnRecorder


class Connection(MCPConnection):
    def __init__(self, name: str, tools: tuple[Tool, ...], *, failure: BaseException | None = None) -> None:
        super().__init__(name, "http://localhost/mcp/")
        self.tools = tools
        self.instructions = f"Guidance for {name}"
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.failure = failure
        self.closed = False

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        self.calls.append((name, arguments))
        if self.failure is not None:
            raise self.failure
        return CallToolResult(
            content=[TextContent(type="text", text=self.name)],
            structured_content={"owner": self.name}, is_error=name == "error",
        )


def tool(name: str = "hello_world") -> Tool:
    return Tool(name=name, description="Say hello", input_schema={
        "type": "object", "properties": {"name": {"type": "string"}},
    })


class Generator:
    def __init__(self, calls: tuple[AgenticToolCall, ...]) -> None:
        self.calls = calls
        self.requests: list[AgenticGenerationRequest] = []

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return AgenticGenerationResponse(tuple(
                {"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments}
                for call in self.calls
            ), self.calls, None)
        return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "Finished"},), (), "Finished")


def local_tool(call: ToolInvocation) -> ToolExecution[Never]:
    return ToolExecution("local result")


def test_two_servers_with_same_tool_route_independently_and_respect_shared_limits() -> None:
    recorder = ToolTurnRecorder[Never]()
    first = Connection("first", (tool(),))
    second = Connection("second", (tool(),))
    source = MCPToolset((first, second))
    generator = Generator((
        AgenticToolCall("a", "first__hello_world", '{"name":"Alice"}'),
        AgenticToolCall("b", "second__hello_world", "{}"),
        AgenticToolCall("c", "first__hello_world", "{}"),
        AgenticToolCall("d", "other__hello_world", "{}"),
    ))
    result = asyncio.run(run_tool_turn(
        generator, (), "Context", "Local guidance",
        (LocalToolSource((RegisteredTool("local", {"type": "function", "name": "local"}, local_tool),)), source),
        2, 1, 2,
        record_item=recorder.record_item, start_execution=recorder.start_execution,
        record_result=recorder.record_result,
    ))
    assert result.kind == "completed" and result.artifacts == ()
    assert first.calls == [("hello_world", {"name": "Alice"})]
    assert second.calls == [("hello_world", {})]
    schemas = generator.requests[0].tools
    assert [schema["name"] for schema in schemas] == ["local", "first__hello_world", "second__hello_world"]
    assert schemas[1]["parameters"] == first.tools[0].input_schema
    assert schemas[1]["strict"] is False
    instructions = generator.requests[0].instructions
    assert "Guidance for first" in instructions and "Guidance for second" in instructions
    assert instructions.endswith("Local guidance")
    outputs = generator.requests[1].input_items[-4:]
    assert [item["call_id"] for item in outputs] == ["a", "b", "c", "d"]
    decoded = [json.loads(str(item["output"])) for item in outputs]
    assert decoded[0]["structuredContent"] == {"owner": "first"}
    assert decoded[1]["content"][0]["text"] == "second"
    assert decoded[2]["kind"] == "limit_reached"
    assert decoded[3]["reason"] == "unknown_tool"
    isolated = MCPToolset((first,))
    assert [registered.name for registered in isolated.registered_tools()] == ["first__hello_world"]
    assert "Guidance for second" not in isolated.instructions


def test_mcp_and_artifact_producing_local_source_execute_in_one_turn() -> None:
    recorder = ToolTurnRecorder[str]()
    connection = Connection("server", (tool(),))
    generator = Generator((
        AgenticToolCall("remote", "server__hello_world", "{}"),
        AgenticToolCall("local", "publish", "{}"),
    ))

    def publish(call: ToolInvocation) -> ToolExecution[str]:
        return ToolExecution("Published", "local artifact")

    local_source = LocalToolSource(
        (RegisteredTool("publish", {"type": "function", "name": "publish"}, publish),),
        instructions="Local capability guidance",
    )
    result = asyncio.run(run_tool_turn(
        generator, (), "Context", "Agent guidance",
        (local_source, MCPToolset((connection,))), 2, 1, 2,
        record_item=recorder.record_item, start_execution=recorder.start_execution,
        record_result=recorder.record_result,
    ))
    assert result.kind == "completed"
    assert result.artifacts == ("local artifact",)
    assert connection.calls == [("hello_world", {})]
    instructions = generator.requests[0].instructions
    assert instructions.index("Local capability guidance") < instructions.index("Guidance for server")
    assert instructions.endswith("Agent guidance")
    assert generator.requests[1].input_items[-1] == {
        "type": "function_call_output", "call_id": "local", "output": "Published",
    }


@pytest.mark.parametrize("arguments", ["broken", "[]", "null", '{"name":NaN}', '{"name":Infinity}'])
def test_invalid_arguments_never_reach_server(arguments: str) -> None:
    connection = Connection("server", (tool(),))
    result = asyncio.run(ToolRegistry(MCPToolset((connection,)).registered_tools()).invoke(
        "server__hello_world", arguments,
    ))
    assert json.loads(result.output)["reason"] == "invalid_arguments"
    assert connection.calls == []


def test_tool_errors_are_returned_and_transport_errors_do_not_leak_details() -> None:
    async def exercise() -> None:
        server = Connection("server", (tool("error"),))
        registry = ToolRegistry(MCPToolset((server,)).registered_tools())
        error = await registry.invoke("server__error", "{}")
        assert json.loads(error.output)["isError"] is True
        assert error.failed is True
        assert json.loads(error.output)["content"][0]["text"] == "server"
        server.failure = RuntimeError("sensitive transport details")
        failed = await registry.invoke("server__error", "{}")
        assert json.loads(failed.output) == {"kind": "tool_failed", "reason": "mcp_call_failed"}
        assert failed.failed is True
        server.failure = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await registry.invoke("server__error", "{}")

    asyncio.run(exercise())


@pytest.mark.parametrize("connections", [
    (Connection("same", (tool(),)), Connection("same", (tool(),))),
    (Connection("", (tool(),)),),
    (Connection("has spaces", (tool(),)),),
])
def test_invalid_connection_names_rejected(connections: tuple[MCPConnection, ...]) -> None:
    with pytest.raises(ValueError, match="connection names"):
        MCPToolset(connections)


@pytest.mark.parametrize("connections", [
    (Connection("server", (tool("invalid.name"),)),),
    (Connection("server", (tool("x" * 60),)),),
    (Connection("server", (tool(), tool())),),
    (Connection("a__b", (tool("c"),)), Connection("a", (tool("b__c"),))),
])
def test_bad_discovered_names_disable_owner_and_close_resources(connections: tuple[MCPConnection, ...]) -> None:
    async def exercise() -> None:
        runtime = AgentRuntime("test", object(), mcp_connections=connections)
        await runtime.start()
        assert runtime.agent is None
        assert all(isinstance(connection, Connection) and connection.closed for connection in connections)

    asyncio.run(exercise())


def test_mcp_and_local_name_collision_is_rejected_before_generation() -> None:
    recorder = ToolTurnRecorder[Never]()
    generator = Generator(())
    connection = Connection("server", (tool(),))
    with pytest.raises(ValueError, match="unique names"):
        asyncio.run(run_tool_turn(
            generator, (), "Context", "Instructions",
            (LocalToolSource((RegisteredTool("server__hello_world", {"type": "function", "name": "server__hello_world"}, local_tool),)),
             MCPToolset((connection,))),
            1, 1, 1,
            record_item=recorder.record_item, start_execution=recorder.start_execution,
            record_result=recorder.record_result,
        ))
    assert generator.requests == []
