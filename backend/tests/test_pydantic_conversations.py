import asyncio
from collections.abc import Sequence

import pytest
from pydantic_ai import RunContext, Tool, models
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.conversations import AgentConversation, ConversationBusyError
from app.agentic.turns import create_turn_agent


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def prompts(messages: Sequence[ModelMessage]) -> list[str]:
    return [
        part.content
        for message in messages for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]


def returns(messages: Sequence[ModelMessage]) -> dict[str, ToolReturnPart]:
    return {
        part.tool_call_id: part
        for message in messages for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


def test_continuation_has_fresh_budgets_and_detached_snapshots() -> None:
    calls: list[str] = []
    toolset = FunctionToolset[None]()

    @toolset.tool_plain
    def lookup(label: str) -> str:
        """Look up a value."""
        calls.append(label)
        return label

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        label = prompts(messages)[-1]
        if label not in returns(messages):
            return ModelResponse(parts=[ToolCallPart("lookup", {"label": label}, label)])
        return ModelResponse(parts=[TextPart(label)])

    async def exercise() -> None:
        conversation = AgentConversation()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        limits = UsageLimits(request_limit=2, tool_calls_limit=1)
        async with agent:
            first = await conversation.run_turn(agent, "first", usage_limits=limits, toolsets=[toolset])
            snapshot = conversation.messages
            assert snapshot == tuple(first.all_messages())
            first.response.parts.clear()
            snapshot[-1].parts.clear()
            inspection = conversation.last_turn
            assert inspection is not None
            inspection.messages.clear()
            inspection.usage.requests = 999
            second = await conversation.run_turn(agent, "second", usage_limits=limits, toolsets=[toolset])
        assert first.run_id != second.run_id
        assert first.conversation_id == second.conversation_id
        assert prompts(conversation.messages) == ["first", "second"]
        assert set(returns(conversation.messages)) == {"first", "second"}
        assert [part.content for msg in conversation.messages for part in msg.parts if isinstance(part, TextPart)] == ["first", "second"]
        assert second.usage.requests == 2
        assert second.usage.tool_calls == 1
        inspection = conversation.last_turn
        assert inspection is not None
        assert inspection.usage == second.usage
        assert [call.tool_call_id for call in inspection.started_calls] == ["second"]
        restored = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(list(conversation.messages)))
        assert restored == list(conversation.messages)
        assert calls == ["first", "second"]

    asyncio.run(exercise())


def test_model_failure_retains_confirmed_results_for_followup_without_replay() -> None:
    calls = 0

    def update() -> int:
        """Update the value."""
        nonlocal calls
        calls += 1
        return 42

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if prompts(messages)[-1] == "followup":
            assert returns(messages)["update"].content == 42
            assert returns(messages)["update"].outcome == "success"
            return ModelResponse(parts=[TextPart("The update was confirmed.")])
        if calls == 0:
            return ModelResponse(parts=[TextPart("Updating."), ToolCallPart("update", {}, "update")])
        raise RuntimeError("Model unavailable")

    async def exercise() -> None:
        conversation = AgentConversation()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(update)])
        async with agent:
            with pytest.raises(RuntimeError, match="Model unavailable"):
                await conversation.run_turn(agent, "update")
            failed = conversation.last_turn
            assert failed is not None
            assert failed.usage.tool_calls == 1
            assert returns(conversation.messages)["update"].content == 42
            assert any(isinstance(part, TextPart) for msg in conversation.messages for part in msg.parts)
            result = await conversation.run_turn(agent, "followup", usage_limits=UsageLimits(request_limit=1))
        assert result.usage.tool_calls == 0
        assert result.conversation_id == failed.conversation_id
        assert calls == 1

    asyncio.run(exercise())


def test_cancellation_retains_uncertain_call_and_releases_busy_guard() -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        cleaned_up = asyncio.Event()
        calls = 0

        async def update() -> str:
            """Update the value."""
            nonlocal calls
            calls += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.set()
            return "Unreachable"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if prompts(messages)[-1] == "followup":
                assert returns(messages)["update"].outcome == "interrupted"
                return ModelResponse(parts=[TextPart("The update outcome is unknown.")])
            return ModelResponse(parts=[ToolCallPart("update", {}, "update")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(update)])
        conversation = AgentConversation()
        async with agent:
            task = asyncio.create_task(conversation.run_turn(agent, "update"))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                with pytest.raises(ConversationBusyError):
                    await conversation.run_turn(agent, "must not be admitted")
                assert conversation.messages == ()
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert cleaned_up.is_set()
            failed = conversation.last_turn
            assert failed is not None
            assert [call.tool_call_id for call in failed.started_calls] == ["update"]
            assert not returns(conversation.messages)
            assert conversation.messages[-1].state == "interrupted"
            result = await conversation.run_turn(agent, "followup")
        assert result.usage.tool_calls == 0
        assert prompts(conversation.messages) == ["update", "followup"]
        assert calls == 1

    asyncio.run(exercise())


def test_independent_conversations_run_concurrently_on_one_agent() -> None:
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
            label = prompts(messages)[-1]
            if not returns(messages):
                return ModelResponse(parts=[ToolCallPart("lookup", {"label": label}, label)])
            return ModelResponse(parts=[TextPart(label)])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        left, right = AgentConversation(), AgentConversation()
        async with agent:
            first, second = await asyncio.gather(left.run_turn(agent, "left"), right.run_turn(agent, "right"))
        assert prompts(left.messages) == ["left"]
        assert prompts(right.messages) == ["right"]
        assert set(returns(left.messages)) == {"left"}
        assert set(returns(right.messages)) == {"right"}
        assert first.conversation_id != second.conversation_id

    asyncio.run(exercise())


def test_budget_failure_retains_requested_call_and_next_turn_gets_fresh_budget() -> None:
    def lookup() -> str:
        """Look up a value."""
        pytest.fail("Budget-rejected call must not execute")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if prompts(messages)[-1] == "followup":
            assert returns(messages)["lookup"].outcome == "interrupted"
            return ModelResponse(parts=[TextPart("The lookup did not execute.")])
        return ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        conversation = AgentConversation()
        async with agent:
            with pytest.raises(UsageLimitExceeded):
                await conversation.run_turn(agent, "lookup", usage_limits=UsageLimits(tool_calls_limit=0))
            failed = conversation.last_turn
            assert failed is not None
            assert failed.started_calls == ()
            result = await conversation.run_turn(agent, "followup", usage_limits=UsageLimits(request_limit=1))
        assert result.usage.requests == 1
        assert result.usage.tool_calls == 0

    asyncio.run(exercise())


def test_setup_failure_does_not_discard_prior_history_or_keep_conversation_busy() -> None:
    class UnavailableTools(FunctionToolset[None]):
        async def for_run(self, ctx: RunContext[None]) -> FunctionToolset[None]:
            raise RuntimeError("Toolset unavailable")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Hello.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        conversation = AgentConversation()
        async with agent:
            await conversation.run_turn(agent, "first")
            history = conversation.messages
            with pytest.raises(RuntimeError, match="Toolset unavailable"):
                await conversation.run_turn(agent, "invalid", toolsets=[UnavailableTools()])
            assert conversation.messages == history
            await conversation.run_turn(agent, "followup")
        assert prompts(conversation.messages) == ["first", "followup"]

    asyncio.run(exercise())
