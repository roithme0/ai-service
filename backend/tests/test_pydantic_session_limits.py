import asyncio
from decimal import Decimal

import pytest
from pydantic_ai import ConversationTypeAdapter, Tool, models
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage, UsageLimits

from app.agentic import limits
from app.agentic.session_state import SessionState
from app.agentic.turns import create_turn_agent


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def test_fifty_requests_across_turns_close_execution_without_losing_history() -> None:
    async def exercise() -> None:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done")])

        session_state = SessionState(initial_context={"recipe": "soup"})
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            for index in range(50):
                result = await session_state.execute_turn(
                    agent, str(index), usage_limits=UsageLimits(request_limit=1),
                )
                assert result.usage.requests == index + 1
            assert session_state.limit_reached
            retained = session_state.conversation
            turn_executions = session_state.turn_executions
            with pytest.raises(limits.ConversationLimitReached, match="Conversation limit reached"):
                await session_state.execute_turn(agent, "Rejected", usage_limits=UsageLimits(request_limit=None))
            assert session_state.conversation == retained
            assert session_state.turn_executions == turn_executions
            restored = ConversationTypeAdapter.validate_json(ConversationTypeAdapter.dump_json(retained))
            assert restored == retained
            assert len([part for message in restored.messages for part in message.parts
                        if isinstance(part, UserPromptPart)]) == 51
            assert all(execution.observation is None for execution in turn_executions)

    asyncio.run(exercise())


def test_conversation_cap_interrupts_a_turn_after_its_remaining_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "MAX_MODEL_REQUESTS_PER_CONVERSATION", 3)
    calls = 0

    def lookup() -> str:
        """Read a value."""
        nonlocal calls
        calls += 1
        return "Value"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("lookup", {}, f"call-{calls}")])

    async def exercise() -> None:
        session_state = SessionState()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        async with agent:
            with pytest.raises(UsageLimitExceeded):
                await session_state.execute_turn(agent, "First", usage_limits=UsageLimits(request_limit=1))
            assert not session_state.limit_reached
            assert session_state.conversation.usage.requests == 1
            with pytest.raises(limits.ConversationLimitReached):
                await session_state.execute_turn(agent, "Second", usage_limits=UsageLimits(request_limit=None))
            assert session_state.conversation.usage.requests == calls == 3
            assert session_state.limit_reached
            assert session_state.turn_executions[-1].lifecycle.status == "failed"
            assert session_state.messages

    asyncio.run(exercise())


def test_parallel_batch_respects_conversation_cap_even_with_unlimited_turn_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "MAX_TOOL_CALLS_PER_CONVERSATION", 3)
    calls = 0

    def lookup() -> str:
        """Read a value."""
        nonlocal calls
        calls += 1
        return "Value"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if messages[-1].kind == "request" and any(isinstance(part, UserPromptPart) for part in messages[-1].parts):
            return ModelResponse(parts=[ToolCallPart("lookup", {}, f"{calls}-{index}") for index in range(2)])
        return ModelResponse(parts=[TextPart("Done")])

    async def exercise() -> None:
        session_state = SessionState()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        async with agent:
            await session_state.execute_turn(agent, "First")
            with pytest.raises(limits.ConversationLimitReached):
                await session_state.execute_turn(agent, "Second", usage_limits=UsageLimits(tool_calls_limit=None))
            assert calls == session_state.conversation.usage.tool_calls == 2
            assert session_state.limit_reached
            assert session_state.turn_executions[-1].lifecycle.status == "failed"
            retained = session_state.conversation
            with pytest.raises(limits.ConversationLimitReached):
                await session_state.execute_turn(agent, "Rejected")
            assert session_state.conversation == retained

    asyncio.run(exercise())


def test_exact_tool_cap_allows_the_final_answer_then_closes_submission() -> None:
    calls = 0

    def lookup() -> str:
        """Read a value."""
        nonlocal calls
        calls += 1
        return "Value"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, UserPromptPart) for part in messages[-1].parts):
            count = 32 if calls == 0 else 8
            return ModelResponse(parts=[ToolCallPart("lookup", {}, f"{calls}-{index}") for index in range(count)])
        return ModelResponse(parts=[TextPart("Final answer")])

    async def exercise() -> None:
        session_state = SessionState()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        async with agent:
            await session_state.execute_turn(agent, "First")
            assert not session_state.limit_reached
            final = await session_state.execute_turn(agent, "Second")
            assert final.output == "Final answer"
            assert final.usage.tool_calls == calls == 40
            assert session_state.turn_executions[-1].lifecycle.status == "completed"
            assert session_state.limit_reached
            with pytest.raises(limits.ConversationLimitReached):
                await session_state.execute_turn(agent, "Rejected")

    asyncio.run(exercise())


def test_caller_token_and_cost_allowances_are_fresh_without_resetting_accounting() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Done")], usage=RequestUsage(
            input_tokens=10, output_tokens=5, cost=Decimal("0.01"),
        ))

    async def exercise() -> None:
        session_state = SessionState()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        allowance = UsageLimits(
            request_limit=1, input_tokens_limit=10, output_tokens_limit=5,
            total_tokens_limit=15, cost_limit=Decimal("0.01"), per_request_input_tokens_limit=10,
        )
        async with agent:
            await session_state.execute_turn(agent, "First", usage_limits=allowance)
            await session_state.execute_turn(agent, "Second", usage_limits=allowance)
            usage = session_state.conversation.usage
            assert usage.input_tokens == 20 and usage.output_tokens == 10
            assert usage.cost == Decimal("0.02")
            with pytest.raises(UsageLimitExceeded):
                await session_state.execute_turn(agent, "Too much", usage_limits=UsageLimits(input_tokens_limit=9))
            assert not session_state.limit_reached
            await session_state.execute_turn(agent, "Retry", usage_limits=allowance)
            assert session_state.conversation.usage.input_tokens == 40
            assert allowance.input_tokens_limit == 10 and allowance.cost_limit == Decimal("0.01")

    asyncio.run(exercise())
