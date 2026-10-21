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
from app.agentic.presentation import AcceptedArtifact, AssistantText, PresentedSession, PresentedTurn, ToolActivity, UserPrompt, present_session
from app.agentic.runner import AgentTurnRunner
from app.agentic.sessions import (
    ObservationLimitError,
    ObservationOverflowError,
    SessionNotFoundError,
    SessionSnapshot,
)
from app.agentic.turns import create_turn_agent
from app.agentic.artifact_models import ArtifactCapability


def groups(snapshot: PresentedSession) -> tuple[PresentedTurn, ...]:
    return tuple(item for item in snapshot.history if isinstance(item, PresentedTurn))


def artifacts(snapshot: PresentedSession) -> tuple[AcceptedArtifact, ...]:
    return tuple(part for group in groups(snapshot) for part in group.parts
                 if isinstance(part, AcceptedArtifact))


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


async def until(
    updates: AsyncIterator[PresentedSession], predicate: Callable[[PresentedSession], bool],
) -> PresentedSession:
    async with asyncio.timeout(5):
        async for snapshot in updates:
            if predicate(snapshot):
                return snapshot
    raise AssertionError("Observation ended before the expected state.")


def has_started(snapshot: PresentedSession) -> bool:
    return any(isinstance(part, ToolActivity) and part.status == "running"
               for group in groups(snapshot) for part in group.parts)


def has_result(snapshot: PresentedSession) -> bool:
    return any(isinstance(part, ToolActivity) and part.status == "success"
               for group in groups(snapshot) for part in group.parts)


def settled(snapshot: PresentedSession) -> bool:
    return bool(groups(snapshot) and groups(snapshot)[-1].lifecycle.status != "running")


def test_observer_sees_presented_progress_and_complete_snapshots_without_internal_data() -> None:
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

        agent = create_turn_agent(FunctionModel(respond), instructions="SECRET_INSTRUCTIONS", tools=[Tool(lookup)])
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice", initial_context={"secret": "SECRET_CONTEXT"})
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as updates:
            initial = await anext(updates)
            assert groups(initial) == ()
            await runner.submit(session.session_id, owner="alice", prompt="Find it.")
            await asyncio.wait_for(started.wait(), 5)
            admitted = await anext(updates)
            assert groups(admitted)[-1].lifecycle.status == "running"
            assert groups(admitted)[-1].lifecycle.run_id is None
            active = await until(updates, has_started)
            assert groups(active)[-1].lifecycle.run_id is not None
            assert groups(active)[-1].parts == (
                AssistantText(content="Looking up."),
                ToolActivity(part_kind="tool-call", tool_name="lookup", tool_call_id="lookup", status="running"),
            )
            assert active.history[0] == UserPrompt(content="Find it.")
            assert runner.read_session(session.session_id, owner="alice") == active
            assert PresentedSession.model_validate_json(active.model_dump_json()) == active
            assert "SECRET" not in active.model_dump_json()
            assert set(active.model_dump()) == {"session_id", "expires_at", "history"}
            release.set()
            await asyncio.wait_for(continuing.wait(), 5)
            returned = await until(updates, has_result)
            assert groups(returned)[-1].lifecycle.status == "running"
            finish.set()
            final = await until(updates, settled)
            assert groups(final)[-1].lifecycle.status == "completed"
            assert groups(final)[-1].parts[-1] == AssistantText(content="Found 42.")
            assert final.history[0] == active.history[0]
            assert has_started(active) and has_result(final)
            assert runner.read_session(session.session_id, owner="alice") == final
            assert "SECRET" not in final.model_dump_json()


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
            published = await until(updates, lambda snapshot: bool(artifacts(snapshot)))
            assert groups(published)[-1].lifecycle.status == "running"
            activity = groups(published)[-1].parts[0]
            assert isinstance(activity, ToolActivity)
            assert activity.part_kind == "tool-call" and activity.tool_call_id == "artifact"
            assert groups(published)[-1].parts[1] == artifacts(published)[0]
            artifacts(published)[0].artifact.payload.payload["consumer"] = "changed"
            assert "consumer" not in artifacts(runner.read_session(session.session_id, owner="alice"))[0].artifact.payload.payload
            artifacts(published)[0].artifact.payload.payload.pop("consumer")
            if outcome == "cancelled":
                await runner.close()
            else:
                release.set()
            final = await until(updates, settled)
            assert groups(final)[-1].lifecycle.status == outcome
            assert artifacts(final) == artifacts(published)
            assert has_result(final)
            await runner.close()
            async for remaining in updates:
                assert groups(remaining)[-1].lifecycle.status == outcome
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
            first_snapshot = await until(first_updates, lambda snapshot: bool(groups(snapshot)))
            assert first_snapshot.session_id == first.session_id
            await first_updates.aclose()
            assert groups(runner.read_session(first.session_id, owner="alice"))[-1].lifecycle.status == "running"
            release.set()
            assert groups(await until(duplicate, settled))[-1].lifecycle.status == "completed"
            assert groups(runner.read_session(second.session_id, owner="bob")) == ()
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
                assert groups(active)[-1].lifecycle.status == "running"
                await replacement.aclose()
            release.set()
            monkeypatch.setattr("app.agentic.sessions.MAX_PENDING_OBSERVATION_UPDATES", MAX_PENDING_OBSERVATION_UPDATES)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as healthy:
                assert groups(await until(healthy, settled))[-1].lifecycle.status == "completed"

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
                assert groups(initial)[-1].lifecycle.status == "running"
                assert initial.history[0] == UserPrompt(content="First.")
                release.set()
                assert groups(await until(late, settled))[-1].lifecycle.status == "completed"
                await runner.submit(session.session_id, owner="alice", prompt="Second.")
                final = await until(late, lambda snapshot: len(groups(snapshot)) == 2 and settled(snapshot))
                assert [turn.lifecycle.status for turn in groups(final)] == ["completed", "completed"]
                assert groups(final)[0].parts == (AssistantText(content="Done."),)
                assert groups(final)[0].lifecycle.run_id != groups(final)[1].lifecycle.run_id

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
            assert groups(final)[-1].lifecycle.status == "failed"
            assert groups(final)[-1].lifecycle.run_id is None
            assert groups(final)[-1].parts == ()
            assert initial.history == ()
            assert all(isinstance(item, PresentedTurn) for item in final.history)

    asyncio.run(exercise())


def test_projection_failure_closes_subscription_and_releases_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Done.")])

        def reject_projection(snapshot: SessionSnapshot) -> PresentedSession:
            raise RuntimeError("Projection failed")

        monkeypatch.setattr("app.agentic.sessions.MAX_OBSERVERS_PER_SESSION", 1)
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice")
        async with agent, runner:
            monkeypatch.setattr("app.agentic.runner.present_session", reject_projection)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as broken:
                with pytest.raises(RuntimeError, match="Projection failed"):
                    await anext(broken)
            monkeypatch.setattr("app.agentic.runner.present_session", present_session)
            async with aclosing(runner.observe_session(session.session_id, owner="alice")) as replacement:
                assert (await anext(replacement)).history == ()
                await runner.submit(session.session_id, owner="alice", prompt="Work.")
                final = await until(replacement, settled)
                assert groups(final)[-1].lifecycle.status == "completed"

    asyncio.run(exercise())
