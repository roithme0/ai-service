import asyncio
import json
from collections.abc import Callable

import pytest

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.text_sessions import TextMessage
from app.sessions.tool_turns import RegisteredTool, ToolExecution, run_tool_turn


class TwoToolGenerator:
    def __init__(self) -> None:
        self.requests: list[AgenticGenerationRequest] = []

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            calls = (
                AgenticToolCall("call-a", "first", "{}"),
                AgenticToolCall("call-b", "second", "{}"),
                AgenticToolCall("call-x", "unadvertised", "{}"),
            )
            return AgenticGenerationResponse(
                output_items=tuple({"type": "function_call", "call_id": call.call_id,
                                    "name": call.name, "arguments": call.arguments} for call in calls),
                tool_calls=calls, text=None,
            )
        return AgenticGenerationResponse((), (), "Finished")


def test_advertised_tools_dispatch_by_name_with_shared_limits() -> None:
    generator = TwoToolGenerator()
    invoked: list[str] = []

    def first(call: AgenticToolCall) -> ToolExecution[str]:
        invoked.append("first")
        return ToolExecution("accepted", "artifact")

    def second(call: AgenticToolCall) -> ToolExecution[str]:
        invoked.append("second")
        return ToolExecution("accepted", "another")

    result = asyncio.run(run_tool_turn(
        generator, (TextMessage("user", "Help"),), "Context", "Instructions",
        (
            RegisteredTool("first", {"type": "function", "name": "first"}, first),
            RegisteredTool("second", {"type": "function", "name": "second"}, second),
        ),
        max_attempts=2, max_successes=1, max_provider_responses=2,
    ))

    assert result.kind == "completed"
    assert result.artifacts == ("artifact",)
    assert invoked == ["first"]
    assert [tool["name"] for tool in generator.requests[0].tools] == ["first", "second"]
    outputs = generator.requests[1].input_items[-3:]
    assert outputs[0]["call_id"] == "call-a"
    assert outputs[0]["output"] == "accepted"
    assert json.loads(outputs[1]["output"])["kind"] == "limit_reached"
    assert json.loads(outputs[2]["output"])["reason"] == "unknown_tool"


def test_each_advertised_name_dispatches_to_its_own_handler() -> None:
    generator = TwoToolGenerator()
    invoked: list[str] = []

    def handler(name: str) -> Callable[[AgenticToolCall], ToolExecution[str]]:
        def execute(call: AgenticToolCall) -> ToolExecution[str]:
            invoked.append(name)
            return ToolExecution(name, name)
        return execute

    result = asyncio.run(run_tool_turn(
        generator, (TextMessage("user", "Help"),), "Context", "Instructions",
        (
            RegisteredTool("first", {"type": "function", "name": "first"}, handler("first")),
            RegisteredTool("second", {"type": "function", "name": "second"}, handler("second")),
        ),
        max_attempts=2, max_successes=2, max_provider_responses=2,
    ))
    assert invoked == ["first", "second"]
    assert result.artifacts == ("first", "second")
    assert json.loads(generator.requests[1].input_items[-1]["output"])["reason"] == "unknown_tool"


def test_tool_registration_rejects_schema_dispatch_mismatch() -> None:
    generator = TwoToolGenerator()

    def execute(call: AgenticToolCall) -> ToolExecution[str]:
        return ToolExecution("unused")

    with pytest.raises(ValueError, match="matching their schemas"):
        asyncio.run(run_tool_turn(
            generator, (TextMessage("user", "Help"),), "Context", "Instructions",
            (RegisteredTool("first", {"type": "function", "name": "second"}, execute),),
            max_attempts=1, max_successes=1, max_provider_responses=2,
        ))
    assert generator.requests == []
