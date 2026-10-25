import asyncio
from collections.abc import Sequence

import httpx2
import pytest
from pydantic_ai import Conversation, Tool, ToolFailed, UnexpectedModelBehavior, models
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import UsageLimits

from app.capabilities.agentic.observation import TurnObservation
from app.capabilities.agentic.turns import create_turn_agent, execute_turn


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def returns(messages: Sequence[ModelMessage]) -> dict[str, ToolReturnPart]:
    return {
        part.tool_call_id: part
        for message in messages for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


def test_capture_uses_native_history_without_streaming_and_detaches_completed_turn() -> None:
    calls = 0

    def lookup() -> int:
        """Look up the value."""
        nonlocal calls
        calls += 1
        return 42

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls == 0:
            return ModelResponse(parts=[TextPart("I'll look that up."), ToolCallPart("lookup", {}, "lookup-1")])
        return ModelResponse(parts=[TextPart("The value is 42.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        first = TurnObservation()
        second = TurnObservation()
        async with agent:
            result = await execute_turn(agent, "Find the value.", observation=first)
            assert list(first.messages) == result.all_messages()
            assert first.usage == result.usage
            assert first.run_id == result.run_id
            assert [call.tool_call_id for call in first.started_tool_calls] == ["lookup-1"]
            assert returns(first.messages)["lookup-1"].outcome == "success"
            text = [part.content for msg in first.messages for part in msg.parts if isinstance(part, TextPart)]
            assert text == ["I'll look that up.", "The value is 42."]
            history = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(first.messages))
            await execute_turn(agent, "Repeat the value.", conversation=Conversation(messages=list(history)), observation=second)
        assert second.started_tool_calls == ()
        assert second.run_id != first.run_id
        assert second.usage.tool_calls == 0
        assert len(second.messages) > len(first.messages)
        result.response.parts.clear()
        assert isinstance(first.messages[-1].parts[0], TextPart)
        assert calls == 1

    asyncio.run(exercise())


def test_lost_response_preserves_completed_output_and_native_followup_does_not_replay() -> None:
    executed: list[str] = []
    requests = 0

    async def update(label: str) -> str:
        """Update the selected value."""
        executed.append(label)
        if label == "lost":
            raise httpx2.ReadError("Response lost after execution")
        return f"Updated {label}"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        if requests == 1:
            return ModelResponse(parts=[
                TextPart("I'll update the values."),
                ToolCallPart("update", {"label": "confirmed"}, "confirmed"),
                ToolCallPart("update", {"label": "lost"}, "lost"),
                ToolCallPart("update", {"label": "unstarted"}, "unstarted"),
            ])
        results = returns(messages)
        assert results["confirmed"].content == "Updated confirmed"
        assert results["confirmed"].outcome == "success"
        assert results["lost"].outcome == results["unstarted"].outcome == "interrupted"
        return ModelResponse(parts=[TextPart("The first update was confirmed; the second outcome is uncertain.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(update, sequential=True)])
        observation = TurnObservation()
        async with agent:
            with pytest.raises(httpx2.ReadError, match="Response lost"):
                await execute_turn(agent, "Update the values.", observation=observation)
            assert [call.tool_call_id for call in observation.started_tool_calls] == ["confirmed", "lost"]
            assert returns(observation.messages)["confirmed"].outcome == "success"
            assert "lost" not in returns(observation.messages)
            tail = observation.messages[-1]
            assert isinstance(tail, ModelRequest)
            assert tail.state == "interrupted"
            assert any(isinstance(part, TextPart) for msg in observation.messages for part in msg.parts)
            history = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(observation.messages))
            result = await execute_turn(agent, "What was confirmed?", conversation=Conversation(messages=list(history)))
            assert result.usage.tool_calls == 0
        assert executed == ["confirmed", "lost"]
        assert requests == 2
        assert "lost" not in returns(observation.messages)

    asyncio.run(exercise())


def test_explicit_failure_keeps_native_failed_outcome_and_allows_answer() -> None:
    calls = 0

    def lookup() -> str:
        """Look up a value."""
        nonlocal calls
        calls += 1
        raise ToolFailed("Unavailable")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls == 0:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup-1")])
        return ModelResponse(parts=[TextPart("The lookup failed.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        observation = TurnObservation()
        async with agent:
            result = await execute_turn(agent, "Find the value.", observation=observation)
        assert result.output == "The lookup failed."
        assert returns(observation.messages)["lookup-1"].outcome == "failed"
        assert len(observation.started_tool_calls) == 1
        assert calls == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["arguments", "budget"])
def test_rejected_calls_are_observed_without_claiming_execution(failure: str) -> None:
    def lookup(label: str) -> str:
        """Look up a value."""
        pytest.fail("A rejected call must not execute")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("lookup", {} if failure == "arguments" else {"label": "x"}, "call")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        observation = TurnObservation()
        limits = UsageLimits(tool_calls_limit=0) if failure == "budget" else None
        async with agent:
            with pytest.raises(UnexpectedModelBehavior if failure == "arguments" else UsageLimitExceeded):
                await execute_turn(agent, "Find it.", observation=observation, usage_limits=limits)
        assert observation.started_tool_calls == ()
        assert any(isinstance(part, ToolCallPart) for msg in observation.messages for part in msg.parts)
        assert not returns(observation.messages)

    asyncio.run(exercise())


def test_model_failure_keeps_successful_tool_result() -> None:
    calls = 0

    def lookup() -> int:
        """Look up a value."""
        nonlocal calls
        calls += 1
        return 42

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls == 0:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, "call")])
        raise RuntimeError("Model unavailable")

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        observation = TurnObservation()
        async with agent:
            with pytest.raises(RuntimeError, match="Model unavailable"):
                await execute_turn(agent, "Find it.", observation=observation)
        assert returns(observation.messages)["call"].content == 42
        assert observation.usage.tool_calls == 1
        assert calls == 1

    asyncio.run(exercise())


def test_cancellation_settles_capture_after_tool_cleanup_and_preserves_exception() -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        cleaned_up = asyncio.Event()

        async def lookup() -> str:
            """Look up a value."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.set()
            return "Unreachable"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[ToolCallPart("lookup", {}, "call")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        observation = TurnObservation()
        async with agent:
            task = asyncio.create_task(execute_turn(agent, "Find it.", observation=observation))
            await asyncio.wait_for(started.wait(), timeout=5)
            assert [call.tool_call_id for call in observation.started_tool_calls] == ["call"]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert cleaned_up.is_set()
        assert observation.messages[-1].state == "interrupted"
        assert not returns(observation.messages)

    asyncio.run(exercise())


def test_concurrent_turns_have_independent_capture_and_capture_cannot_be_reused() -> None:
    async def exercise() -> None:
        both_started = asyncio.Event()
        labels: set[str] = set()

        async def lookup(label: str) -> str:
            """Look up a value."""
            labels.add(label)
            if len(labels) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=5)
            return label

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompt = next(part for msg in messages for part in msg.parts if isinstance(part, UserPromptPart))
            assert isinstance(prompt.content, str)
            if not returns(messages):
                return ModelResponse(parts=[ToolCallPart("lookup", {"label": prompt.content}, prompt.content)])
            return ModelResponse(parts=[TextPart(prompt.content)])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        left, right = TurnObservation(), TurnObservation()
        async with agent:
            await asyncio.gather(
                execute_turn(agent, "left", observation=left),
                execute_turn(agent, "right", observation=right),
            )
            with pytest.raises(ValueError, match="new TurnObservation"):
                await execute_turn(agent, "again", observation=left)
        assert [call.tool_call_id for call in left.started_tool_calls] == ["left"]
        assert [call.tool_call_id for call in right.started_tool_calls] == ["right"]
        assert set(returns(left.messages)) == {"left"}
        assert set(returns(right.messages)) == {"right"}
        assert left.run_id != right.run_id

    asyncio.run(exercise())
