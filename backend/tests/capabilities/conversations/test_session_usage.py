import asyncio
from decimal import Decimal
from typing import Literal

import pytest
from pydantic_ai import Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage

from app.capabilities.conversations.presentation import PresentedTurn, present_session
from app.capabilities.conversations.sessions import AgentSessionRegistry
from app.capabilities.conversations.session_state import SessionState
from app.capabilities.conversations.turns import create_turn_agent
from app.core.identity import ApplicationIdentity


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_usage_across_turns_and_live_snapshots(
    outcome: Literal["completed", "failed", "cancelled"],
) -> None:
    async def exercise() -> None:
        registry = AgentSessionRegistry()
        owner = ApplicationIdentity("test", "alice")
        created = registry.create(owner=owner)
        started, release = asyncio.Event(), asyncio.Event()
        requests = 0

        async def operation() -> str:
            """Wait for the operation to finish."""
            started.set()
            await release.wait()
            return "Done"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal requests
            requests += 1
            if requests == 3 and outcome == "failed":
                raise RuntimeError("Model failed after tool execution")
            return ModelResponse(
                parts=(
                    [ToolCallPart("operation", {}, "operation")]
                    if requests == 2
                    else [TextPart("Done")]
                ),
                usage=RequestUsage(
                    input_tokens=100,
                    output_tokens=20,
                    cache_read_tokens=30,
                    cache_write_tokens=10,
                    output_reasoning_tokens=5,
                    details={"custom_tokens": 7},
                    cost=Decimal("0.0123"),
                ),
            )

        def read_usage() -> RunUsage:
            return registry.read(created.session_id, owner=owner).usage

        assert read_usage() == RunUsage()
        agent = create_turn_agent(
            FunctionModel(respond), instructions="Help.", tools=[Tool(operation)]
        )
        async with agent:
            first = await registry.execute_turn(
                created.session_id, owner=owner, agent=agent, prompt="First"
            )
            first_snapshot = registry.read(created.session_id, owner=owner)
            assert first_snapshot.usage == first.usage
            assert first_snapshot.turn_executions[0].usage == first.usage
            task = asyncio.create_task(
                registry.execute_turn(
                    created.session_id, owner=owner, agent=agent, prompt="Second"
                )
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                active = registry.read(created.session_id, owner=owner)
                turn = active.turn_executions[-1]
                assert active.usage.requests == 2
                assert active.usage.input_tokens == 200
                assert active.usage.cost == Decimal("0.0246")
                assert turn.usage.requests == 1
                assert turn.usage.input_tokens == 100
                assert turn.usage.output_tokens == 20
                assert turn.usage.total_tokens == 120
                assert turn.usage.cache_read_tokens == 30
                assert turn.usage.cache_write_tokens == 10
                assert turn.usage.output_reasoning_tokens == 5
                assert turn.usage.cost == Decimal("0.0123")
                assert turn.usage.details == {"custom_tokens": 7}
                assert active.usage.details == {"custom_tokens": 14}
                assert read_usage().details == {"custom_tokens": 14}
                assert active.conversation.usage.requests == 1
                presented = present_session(active).model_dump(mode="json")
                expected = {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cache_read_tokens": 30,
                    "cache_write_tokens": 10,
                    "reasoning_tokens": 5,
                    "requests": 1,
                    "tool_calls": 0,
                    "estimated_cost_usd": "0.0123",
                }
                public_turns = [
                    item for item in presented["history"] if item["part_kind"] == "turn"
                ]
                assert [item["usage"] for item in public_turns] == [expected, expected]
                assert presented["usage"] == {
                    **{
                        key: value * 2
                        for key, value in expected.items()
                        if isinstance(value, int)
                    },
                    "estimated_cost_usd": "0.0246",
                }
                assert "custom_tokens" not in str(presented)

                if outcome == "cancelled":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    if outcome == "failed":
                        with pytest.raises(RuntimeError, match="Model failed"):
                            await asyncio.wait_for(task, timeout=5)
                    else:
                        await asyncio.wait_for(task, timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task

            settled = registry.read(created.session_id, owner=owner)
            completed_responses = 2 if outcome == "completed" else 1
            retained = settled.turn_executions[-1]
            assert retained.lifecycle.status == outcome
            assert retained.observation is None
            assert retained.usage.requests == completed_responses
            assert retained.usage.tool_calls == (0 if outcome == "cancelled" else 1)
            assert retained.usage.input_tokens == 100 * completed_responses
            assert retained.usage.cost == Decimal("0.0123") * completed_responses
            assert settled.usage == settled.conversation.usage
            assert settled.usage.requests == 1 + completed_responses
            public = present_session(settled)
            public_turn = public.history[-1]
            assert isinstance(public_turn, PresentedTurn)
            assert public_turn.usage.requests == completed_responses
            assert public_turn.usage.tool_calls == (0 if outcome == "cancelled" else 1)
            assert public_turn.usage.estimated_cost_usd == retained.usage.cost
            assert public.usage.requests == 1 + completed_responses
            assert settled.usage.details == {
                "custom_tokens": 7 * (1 + completed_responses)
            }
            assert first_snapshot.usage.requests == 1
            assert active.usage.requests == 2

            detached_total = settled.usage
            detached_total.details.clear()
            detached_total.input_tokens = 999
            retained.usage.details.clear()
            retained.usage.input_tokens = 999
            assert read_usage().input_tokens == 100 * (1 + completed_responses)
            assert registry.read(created.session_id, owner=owner).turn_executions[
                -1
            ].usage.details == {"custom_tokens": 7 * completed_responses}

            await registry.execute_turn(
                created.session_id, owner=owner, agent=agent, prompt="Follow-up"
            )
            final = registry.read(created.session_id, owner=owner)
            assert final.turn_executions[-1].usage.requests == 1
            assert final.turn_executions[-1].usage.cost == Decimal("0.0123")
            assert final.usage.requests == 2 + completed_responses

    asyncio.run(exercise())


@pytest.mark.parametrize("cancelled", [False, True])
def test_failure_before_capture_retains_baseline_without_charging_new_turn(
    cancelled: bool,
) -> None:
    async def exercise() -> None:
        state = SessionState()

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(
                parts=[TextPart("Done")],
                usage=RequestUsage(input_tokens=10, cost=Decimal("0.01")),
            )

        def fail_setup() -> None:
            active = state.turn_executions[-1]
            assert active.lifecycle.run_id is None
            assert active.usage == RunUsage()
            assert active.observation is not None
            assert active.observation.usage == state.conversation.usage
            if cancelled:
                raise asyncio.CancelledError
            raise RuntimeError("Setup failed")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            await state.execute_turn(agent, "First")
            baseline = state.conversation
            with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
                await state.execute_turn(agent, "Setup", on_admitted=fail_setup)
            failed = state.turn_executions[-1]
            assert failed.lifecycle.status == ("cancelled" if cancelled else "failed")
            assert failed.usage == RunUsage()
            assert state.conversation == baseline
            await state.execute_turn(agent, "Follow-up")
            assert state.turn_executions[-1].usage.input_tokens == 10
            assert state.conversation.usage.input_tokens == 20

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "costs, expected_turn_costs, expected_total",
    [
        ([None, None], [None, None], None),
        ([Decimal("0"), Decimal("0")], [Decimal("0"), None], Decimal("0")),
        ([Decimal("0.01"), None], [Decimal("0.01"), None], Decimal("0.01")),
        ([None, Decimal("0.01")], [None, Decimal("0.01")], Decimal("0.01")),
    ],
)
def test_costs_preserve_native_unknown_zero_and_subtotal_semantics(
    costs: list[Decimal | None],
    expected_turn_costs: list[Decimal | None],
    expected_total: Decimal | None,
) -> None:
    async def exercise() -> None:
        registry = AgentSessionRegistry()
        owner = ApplicationIdentity("test", "alice")
        created = registry.create(owner=owner)
        requests = 0

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal requests
            cost = costs[requests]
            requests += 1
            return ModelResponse(
                parts=[TextPart("Done")],
                usage=RequestUsage(input_tokens=10, output_tokens=5, cost=cost),
            )

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            for index in range(len(costs)):
                await registry.execute_turn(
                    created.session_id, owner=owner, agent=agent, prompt=str(index)
                )
        snapshot = registry.read(created.session_id, owner=owner)
        assert [
            turn.usage.cost for turn in snapshot.turn_executions
        ] == expected_turn_costs
        assert snapshot.usage.cost == expected_total
        assert snapshot.usage.input_tokens == 20
        public = present_session(snapshot).model_dump(mode="json")
        assert public["usage"]["estimated_cost_usd"] == (
            str(expected_total) if expected_total is not None else None
        )
        assert [
            item["usage"]["estimated_cost_usd"]
            for item in public["history"]
            if item["part_kind"] == "turn"
        ] == [str(cost) if cost is not None else None for cost in expected_turn_costs]

    asyncio.run(exercise())
