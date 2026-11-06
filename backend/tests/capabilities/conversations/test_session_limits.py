import asyncio
from decimal import Decimal

import pytest
from pydantic_ai import ConversationTypeAdapter, Tool, models
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage, UsageLimits

from app.capabilities.conversations.session_state import SessionState
from app.capabilities.conversations.turns import create_turn_agent


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def test_requests_and_tools_continue_past_previous_conversation_caps() -> None:
    calls = 0

    def lookup() -> str:
        """Read a value."""
        nonlocal calls
        calls += 1
        return "Value"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, UserPromptPart) for part in messages[-1].parts):
            return ModelResponse(parts=[ToolCallPart("lookup", {}, f"call-{calls}")])
        return ModelResponse(parts=[TextPart("Done")])

    async def exercise() -> None:
        session_state = SessionState(initial_context={"recipe": "soup"})
        agent = create_turn_agent(
            FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)]
        )
        allowance = UsageLimits(request_limit=2, tool_calls_limit=1)
        async with agent:
            for index in range(51):
                result = await session_state.execute_turn(
                    agent, str(index), usage_limits=allowance
                )
                assert result.usage.requests == (index + 1) * 2
                assert result.usage.tool_calls == index + 1
            retained = session_state.conversation
            restored = ConversationTypeAdapter.validate_json(
                ConversationTypeAdapter.dump_json(retained)
            )
            assert restored == retained
            assert calls == 51
            assert len(session_state.turn_executions) == 51
            assert all(
                execution.observation is None
                and execution.lifecycle.status == "completed"
                for execution in session_state.turn_executions
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "allowance",
    [
        UsageLimits(request_limit=1),
        UsageLimits(tool_calls_limit=1),
    ],
)
def test_turn_limits_reset_after_failure(allowance: UsageLimits) -> None:
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
        agent = create_turn_agent(
            FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)]
        )
        async with agent:
            for index in range(2):
                with pytest.raises(UsageLimitExceeded):
                    await session_state.execute_turn(
                        agent, str(index), usage_limits=allowance
                    )
                assert calls == index + 1
                assert session_state.turn_executions[-1].lifecycle.status == "failed"
            assert session_state.messages

    asyncio.run(exercise())


def test_caller_token_and_cost_allowances_are_fresh_without_resetting_accounting() -> (
    None
):
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[TextPart("Done")],
            usage=RequestUsage(
                input_tokens=10,
                output_tokens=5,
                cost=Decimal("0.01"),
            ),
        )

    async def exercise() -> None:
        session_state = SessionState()
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        allowance = UsageLimits(
            request_limit=1,
            input_tokens_limit=10,
            output_tokens_limit=5,
            total_tokens_limit=15,
            cost_limit=Decimal("0.01"),
            per_request_input_tokens_limit=10,
        )
        async with agent:
            await session_state.execute_turn(agent, "First", usage_limits=allowance)
            await session_state.execute_turn(agent, "Second", usage_limits=allowance)
            usage = session_state.conversation.usage
            assert usage.input_tokens == 20 and usage.output_tokens == 10
            assert usage.cost == Decimal("0.02")
            with pytest.raises(UsageLimitExceeded):
                await session_state.execute_turn(
                    agent, "Too much", usage_limits=UsageLimits(input_tokens_limit=9)
                )
            await session_state.execute_turn(agent, "Retry", usage_limits=allowance)
            assert session_state.conversation.usage.input_tokens == 40
            assert (
                allowance.input_tokens_limit == 10
                and allowance.cost_limit == Decimal("0.01")
            )

    asyncio.run(exercise())
