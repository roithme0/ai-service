import asyncio
import json
from collections.abc import Callable
from typing import Never

import pytest

from app.agents.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.models.history import CallRecord, ContinuationRecord, HistoryRecord
from app.agents.tool_turns import run_tool_turn
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.tools import LocalToolSource
from app.sessions.models.execution import ToolExecution
from tool_turn_recorder import ToolTurnRecorder


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
        return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "Finished"},), (), "Finished")


def test_advertised_tools_dispatch_by_name_with_shared_limits() -> None:
    recorder = ToolTurnRecorder[str]()
    generator = TwoToolGenerator()
    invoked: list[str] = []

    def first(call: ToolInvocation) -> ToolExecution[str]:
        assert [record.call.call_id for record in recorder.calls] == ["call-a", "call-b", "call-x"]
        assert recorder.started == [recorder.calls[0]]
        invoked.append("first")
        return ToolExecution("accepted", "artifact")

    def second(call: ToolInvocation) -> ToolExecution[str]:
        invoked.append("second")
        return ToolExecution("accepted", "another")

    result = asyncio.run(run_tool_turn(
        generator, ({"role": "user", "content": "Help"},), "Context", "Instructions",
        (
            LocalToolSource((RegisteredTool("first", {"type": "function", "name": "first"}, first),)),
            LocalToolSource((RegisteredTool("second", {"type": "function", "name": "second"}, second),)),
        ),
        max_attempts=2, max_successes=1, max_provider_responses=2,
        record_item=recorder.record_item, start_execution=recorder.start_execution,
        record_result=recorder.record_result,
    ))

    assert result.kind == "completed"
    assert result.artifacts == ("artifact",)
    assert invoked == ["first"]
    assert recorder.started == [recorder.calls[0]]
    assert [call for call, _ in recorder.results] == recorder.calls
    assert [tool["name"] for tool in generator.requests[0].tools] == ["first", "second"]
    outputs = generator.requests[1].input_items[-3:]
    assert outputs[0]["call_id"] == "call-a"
    assert outputs[0]["output"] == "accepted"
    limited_output = outputs[1]["output"]
    unknown_output = outputs[2]["output"]
    assert isinstance(limited_output, str) and isinstance(unknown_output, str)
    assert json.loads(limited_output)["kind"] == "limit_reached"
    assert json.loads(unknown_output)["reason"] == "unknown_tool"


def test_each_advertised_name_dispatches_to_its_own_handler() -> None:
    recorder = ToolTurnRecorder[str]()
    generator = TwoToolGenerator()
    invoked: list[str] = []

    def handler(name: str) -> Callable[[ToolInvocation], ToolExecution[str]]:
        def execute(call: ToolInvocation) -> ToolExecution[str]:
            invoked.append(name)
            return ToolExecution(name, name)
        return execute

    result = asyncio.run(run_tool_turn(
        generator, ({"role": "user", "content": "Help"},), "Context", "Instructions",
        (LocalToolSource((
            RegisteredTool("first", {"type": "function", "name": "first"}, handler("first")),
            RegisteredTool("second", {"type": "function", "name": "second"}, handler("second")),
        )),),
        max_attempts=2, max_successes=2, max_provider_responses=2,
        record_item=recorder.record_item, start_execution=recorder.start_execution,
        record_result=recorder.record_result,
    ))
    assert invoked == ["first", "second"]
    assert result.artifacts == ("first", "second")
    unknown_output = generator.requests[1].input_items[-1]["output"]
    assert isinstance(unknown_output, str)
    assert json.loads(unknown_output)["reason"] == "unknown_tool"


def test_tool_registration_rejects_schema_dispatch_mismatch() -> None:
    recorder = ToolTurnRecorder[str]()
    generator = TwoToolGenerator()

    def execute(call: ToolInvocation) -> ToolExecution[str]:
        return ToolExecution("unused")

    with pytest.raises(ValueError, match="matching their schemas"):
        asyncio.run(run_tool_turn(
            generator, ({"role": "user", "content": "Help"},), "Context", "Instructions",
            (LocalToolSource((RegisteredTool("first", {"type": "function", "name": "second"}, execute),)),),
            max_attempts=1, max_successes=1, max_provider_responses=2,
            record_item=recorder.record_item, start_execution=recorder.start_execution,
            record_result=recorder.record_result,
        ))
    assert generator.requests == []


class IndependentToolSource:
    def __init__(self, name: str, instructions: str, invoked: list[str]) -> None:
        self.name = name
        self.instructions = instructions
        self.invoked = invoked

    def registered_tools(self) -> tuple[RegisteredTool[Never], ...]:
        def execute(call: ToolInvocation) -> ToolExecution[Never]:
            self.invoked.append(self.name)
            return ToolExecution(self.name)

        return (RegisteredTool(self.name, {"type": "function", "name": self.name}, execute),)


def test_independent_sources_combine_tools_and_instructions_in_configured_order() -> None:
    recorder = ToolTurnRecorder[Never]()
    generator = TwoToolGenerator()
    invoked: list[str] = []
    first = IndependentToolSource("first", "First source guidance", invoked)
    second = IndependentToolSource("second", "Second source guidance", invoked)
    result = asyncio.run(run_tool_turn(
        generator, (), "Context", "Local instructions", (first, second),
        max_attempts=2, max_successes=1, max_provider_responses=2,
        record_item=recorder.record_item, start_execution=recorder.start_execution,
        record_result=recorder.record_result,
    ))
    assert result.kind == "completed" and result.artifacts == ()
    assert invoked == ["first", "second"]
    assert [tool["name"] for tool in generator.requests[0].tools] == ["first", "second"]
    instructions = generator.requests[0].instructions
    assert instructions.index(first.instructions) < instructions.index(second.instructions)
    assert instructions.count("Local agent instructions") == 1
    assert instructions.endswith("Local instructions")
    assert generator.requests[1].instructions == instructions
    assert [item["output"] for item in generator.requests[1].input_items[-3:-1]] == ["first", "second"]


def test_collision_between_independent_sources_is_rejected_before_generation() -> None:
    recorder = ToolTurnRecorder[Never]()
    generator = TwoToolGenerator()
    invoked: list[str] = []
    with pytest.raises(ValueError, match="unique names"):
        asyncio.run(run_tool_turn(
            generator, (), "Context", "Local instructions", (
                IndependentToolSource("same", "First guidance", invoked),
                IndependentToolSource("same", "Second guidance", invoked),
            ), 2, 1, 2,
            record_item=recorder.record_item, start_execution=recorder.start_execution,
            record_result=recorder.record_result,
        ))
    assert generator.requests == []
    assert invoked == []


@pytest.mark.parametrize("omit", [False, True])
def test_mismatched_recorded_calls_fail_before_execution(omit: bool) -> None:
    generator = TwoToolGenerator()
    recorder = ToolTurnRecorder[str]()
    invoked: list[str] = []

    def record_item(item: dict[str, object]) -> HistoryRecord:
        recorded = recorder.record_item(item)
        if isinstance(recorded, CallRecord):
            return ContinuationRecord("test-turn", item) if omit else CallRecord("test-turn", recorded.execution_id,
                {**item, "name": "different"})
        return recorded

    def execute(call: ToolInvocation) -> ToolExecution[str]:
        invoked.append(call.name)
        return ToolExecution("accepted")

    with pytest.raises(ValueError, match="recorded calls must match"):
        asyncio.run(run_tool_turn(
            generator, (), "Context", "Instructions",
            (LocalToolSource((RegisteredTool("first", {"type": "function", "name": "first"}, execute),)),),
            2, 1, 2, record_item=record_item,
            start_execution=recorder.start_execution, record_result=recorder.record_result,
        ))
    assert len(generator.requests) == 1
    assert invoked == []
    assert recorder.started == recorder.results == []
