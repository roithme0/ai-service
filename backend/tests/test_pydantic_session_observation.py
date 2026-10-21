import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, aclosing
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agentic.config import MAX_OBSERVERS_PER_SESSION, MAX_PENDING_OBSERVATION_UPDATES
from app.agentic.conversations import AgentConversation
from app.agentic.runner import AgentTurnRunner
from app.agentic.sessions import (
    ObservationLimitError,
    ObservationOverflowError,
    SessionNotFoundError,
    SessionSnapshot,
)
from app.agentic.turns import create_turn_agent
from app.sessions.models.artifacts import ArtifactCapability


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


async def until(
    updates: AsyncIterator[SessionSnapshot], predicate: Callable[[SessionSnapshot], bool],
) -> SessionSnapshot:
    async with asyncio.timeout(5):
        async for snapshot in updates:
            if predicate(snapshot):
                return snapshot
    raise AssertionError("Observation ended before the expected state.")


def has_started(snapshot: SessionSnapshot) -> bool:
    return bool(snapshot.turns and snapshot.turns[-1].observation
                and snapshot.turns[-1].observation.started_calls)


def has_result(snapshot: SessionSnapshot) -> bool:
    observation = snapshot.turns[-1].observation if snapshot.turns else None
    return observation is not None and any(
        isinstance(part, ToolReturnPart) for message in observation.messages for part in message.parts
    )


def settled(snapshot: SessionSnapshot) -> bool:
    return bool(snapshot.turns and snapshot.turns[-1].lifecycle.status != "running")


def test_observer_sees_native_progress_usage_and_settlement_without_history_aliasing() -> None:
    async def exercise() -> None:
        started, release, continuing, finish = (asyncio.Event() for _ in range(4))

        async def lookup() -> int:
            """Look up a value."""
            started.set()
            await release.wait()
            return 42

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not any(isinstance(part, ToolReturnPart) for msg in messages for part in msg.parts):
                return ModelResponse(parts=[TextPart("Looking up."), ToolCallPart("lookup", {}, "lookup")])
            continuing.set()
            await finish.wait()
            return ModelResponse(parts=[TextPart("Found 42.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice")
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as updates:
            initial = await anext(updates)
            assert initial.turns == ()
            await runner.submit(session.session_id, owner="alice", prompt="Find it.")
            await asyncio.wait_for(started.wait(), 5)
            admitted = await anext(updates)
            assert admitted.turns[-1].lifecycle.status == "running"
            assert admitted.turns[-1].lifecycle.run_id is None
            active = await until(updates, has_started)
            observation = active.turns[-1].observation
            assert observation is not None
            assert observation.run_id == active.turns[-1].lifecycle.run_id
            assert observation.usage.requests == 1
            assert [call.tool_call_id for call in observation.started_calls] == ["lookup"]
            assert any(isinstance(part, TextPart) and part.content == "Looking up."
                       for msg in observation.messages for part in msg.parts)
            assert active.messages == ()  # Settled history remains a separate read contract.
            observation.messages.clear()
            observation.usage.requests = 999
            fresh = runner.read_session(session.session_id, owner="alice").turns[-1].observation
            assert fresh is not None and fresh.messages and fresh.usage.requests == 1
            release.set()
            await asyncio.wait_for(continuing.wait(), 5)
            returned = await until(updates, has_result)
            assert returned.turns[-1].lifecycle.status == "running"
            finish.set()
            final = await until(updates, settled)
            assert final.turns[-1].lifecycle.status == "completed"
            assert final.last_turn is not None and final.last_turn.usage.requests == 2
            assert observation.usage.requests == 999
            assert final.last_turn.messages[-1].parts == [TextPart("Found 42.")]
            final.messages[-1].parts.clear()
            assert runner.read_session(session.session_id, owner="alice").messages[-1].parts

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_artifacts_survive_outcomes_and_shutdown_delivers_final_snapshot(outcome: str) -> None:
    async def exercise() -> None:
        continuing, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not any(isinstance(part, ToolReturnPart) for msg in messages for part in msg.parts):
                return ModelResponse(parts=[ToolCallPart("present_artifact", {"candidate": {
                    "type": "example", "payload": {"title": "Example", "payload": {}},
                }}, "artifact")])
            continuing.set()
            await release.wait()
            if outcome == "failed":
                raise RuntimeError("Provider failure")
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice", artifact_capabilities=[ArtifactCapability(
            type="example", description="Present data.", payloadSchema={"type": "object"},
        )])
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as updates:
            await anext(updates)
            await runner.submit(session.session_id, owner="alice", prompt="Present.")
            await asyncio.wait_for(continuing.wait(), 5)
            published = await until(updates, lambda snapshot: bool(snapshot.artifacts))
            assert published.turns[-1].lifecycle.status == "running"
            assert published.artifacts[0].tool_call_id == "artifact"
            if outcome == "cancelled":
                await runner.close()
            else:
                release.set()
            final = await until(updates, settled)
            assert final.turns[-1].lifecycle.status == outcome
            assert final.artifacts == published.artifacts
            assert final.last_turn is not None and has_result(final)
            await runner.close()
            async for remaining in updates:
                assert remaining.turns[-1].lifecycle.status == outcome
        async with aclosing(runner.observe_session(session.session_id, owner="alice")) as after_close:
            assert settled(await anext(after_close))
            with pytest.raises(StopAsyncIteration):
                await anext(after_close)

    asyncio.run(exercise())


def test_observers_are_independent_and_disconnect_does_not_cancel_execution() -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        first = runner.create_session(owner="alice")
        second = runner.create_session(owner="bob")
        async with agent, runner, AsyncExitStack() as stack:
            first_updates = await stack.enter_async_context(aclosing(runner.observe_session(first.session_id, owner="alice")))
            duplicate = await stack.enter_async_context(aclosing(runner.observe_session(first.session_id, owner="alice")))
            second_updates = await stack.enter_async_context(aclosing(runner.observe_session(second.session_id, owner="bob")))
            await anext(first_updates)
            await anext(duplicate)
            await anext(second_updates)
            await runner.submit(first.session_id, owner="alice", prompt="Work.")
            await asyncio.wait_for(started.wait(), 5)
            first_snapshot = await until(first_updates, lambda snapshot: bool(snapshot.turns))
            assert first_snapshot.session_id == first.session_id
            await first_updates.aclose()
            assert runner.read_session(first.session_id, owner="alice").turns[-1].lifecycle.status == "running"
            release.set()
            assert (await until(duplicate, settled)).turns[-1].lifecycle.status == "completed"
            assert runner.read_session(second.session_id, owner="bob").turns == ()
            await runner.close()
            with pytest.raises(StopAsyncIteration):
                await anext(second_updates)

    asyncio.run(exercise())


def test_owner_expiry_and_observer_limits_release_slots() -> None:
    async def exercise() -> None:
        now = datetime(2026, 10, 21, tzinfo=UTC)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent, clock=lambda: now)
        session = runner.create_session(owner="alice")
        async with agent, runner, AsyncExitStack() as stack:
            for session_id, owner in ((session.session_id, "bob"), ("missing", "alice")):
                async with aclosing(runner.observe_session(session_id, owner=owner)) as denied:
                    with pytest.raises(SessionNotFoundError):
                        await anext(denied)
            observers = [await stack.enter_async_context(aclosing(runner.observe_session(session.session_id, owner="alice")))
                         for _ in range(MAX_OBSERVERS_PER_SESSION)]
            for updates in observers:
                await anext(updates)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as excess:
                with pytest.raises(ObservationLimitError):
                    await anext(excess)
            # A denied owner must not learn that all observer slots are occupied.
            with pytest.raises(SessionNotFoundError):
                await anext(runner.observe_session(session.session_id, owner="bob"))
            await observers.pop().aclose()
            replacement = await stack.enter_async_context(aclosing(runner.observe_session(session.session_id, owner="alice")))
            await anext(replacement)
            now = session.expires_at - timedelta(milliseconds=10)
            pending = asyncio.create_task(anext(replacement))
            await asyncio.sleep(0)
            now = session.expires_at
            with pytest.raises(SessionNotFoundError):
                await asyncio.wait_for(pending, 5)
            with pytest.raises(SessionNotFoundError):
                await anext(runner.observe_session(session.session_id, owner="alice"))

    asyncio.run(exercise())


def test_slow_observer_overflow_is_explicit_and_does_not_fail_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        continuing, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            continuing.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        monkeypatch.setattr("app.agentic.sessions.MAX_PENDING_OBSERVATION_UPDATES", 1)
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice")
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as slow:
            await anext(slow)
            await runner.submit(session.session_id, owner="alice", prompt="Work.")
            await asyncio.wait_for(continuing.wait(), 5)
            with pytest.raises(ObservationOverflowError):
                await anext(slow)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as replacement:
                active = await anext(replacement)
                assert active.turns[-1].lifecycle.status == "running"
                await replacement.aclose()
            release.set()
            monkeypatch.setattr("app.agentic.sessions.MAX_PENDING_OBSERVATION_UPDATES", MAX_PENDING_OBSERVATION_UPDATES)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as healthy:
                assert (await until(healthy, settled)).turns[-1].lifecycle.status == "completed"

    asyncio.run(exercise())


def test_cancelling_waiting_observer_releases_capacity_and_late_observer_follows_multiple_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        monkeypatch.setattr("app.agentic.sessions.MAX_OBSERVERS_PER_SESSION", 1)
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice")
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as disconnected:
            await anext(disconnected)
            waiting = asyncio.create_task(anext(disconnected))
            await asyncio.sleep(0)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            await runner.submit(session.session_id, owner="alice", prompt="First.")
            await asyncio.wait_for(started.wait(), 5)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as late:
                initial = await anext(late)
                assert initial.turns[-1].lifecycle.status == "running"
                assert initial.turns[-1].observation is not None
                assert initial.turns[-1].observation.messages
                release.set()
                assert (await until(late, settled)).turns[-1].lifecycle.status == "completed"
                await runner.submit(session.session_id, owner="alice", prompt="Second.")
                final = await until(late, lambda snapshot: len(snapshot.turns) == 2 and settled(snapshot))
                assert [turn.lifecycle.status for turn in final.turns] == ["completed", "completed"]
                assert final.turns[0].observation is None
                assert final.turns[0].lifecycle.run_id != final.turns[1].lifecycle.run_id

    asyncio.run(exercise())


def test_observer_sees_setup_failure_without_native_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise AssertionError("Setup failed before model execution.")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice", initial_context={"recipe": 42})
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as updates:
            initial = await anext(updates)

            def reject_history(self: AgentConversation) -> tuple[ModelMessage, ...]:
                raise RuntimeError("Setup unavailable")

            with monkeypatch.context() as setup_patch:
                setup_patch.setattr(AgentConversation, "messages", property(reject_history))
                await runner.submit(session.session_id, owner="alice", prompt="Work.")
                final = await until(updates, settled)
            assert final.turns[-1].lifecycle.status == "failed"
            assert final.turns[-1].lifecycle.run_id is None
            assert final.turns[-1].observation is None
            assert final.messages == initial.messages

    asyncio.run(exercise())
