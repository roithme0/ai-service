import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from pydantic_ai import RunContext, Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agentic.conversations import ConversationBusyError
from app.agentic.sessions import AgentSessionRegistry, SessionNotFoundError
from app.agentic.turns import create_turn_agent
from app.agentic.artifacts import ArtifactCapability


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_active_and_settled_lifecycle_preserves_native_data(outcome: str) -> None:
    registry = AgentSessionRegistry()
    created = registry.create(owner="alice", artifact_capabilities=[ArtifactCapability(
        type="example", description="Present data.", payloadSchema={"type": "object"},
    )])
    other = registry.create(owner="bob")
    failure = RuntimeError("Later model failure")

    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        followup_started, followup_release = asyncio.Event(), asyncio.Event()

        async def operation() -> str:
            """Perform a domain operation."""
            started.set()
            await release.wait()
            return "Done"

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts = [part.content for message in messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            if prompts[-1] == "followup":
                assert "overlap" not in prompts
                followup_started.set()
                await followup_release.wait()
                return ModelResponse(parts=[TextPart("Follow-up.")])
            if len(messages) == 1:
                return ModelResponse(parts=[
                    ToolCallPart("present_artifact", {
                        "type": "example", "content": {"title": "Accepted", "payload": {}},
                    }, "artifact"),
                    ToolCallPart("operation", {}, "operation"),
                ])
            if outcome == "failed":
                raise failure
            return ModelResponse(parts=[TextPart("Finished.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(operation)])
        before = datetime.now(UTC)
        assert registry.read(created.session_id, owner="alice").turns == ()
        async with agent:
            task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="work",
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                active = registry.read(created.session_id, owner="alice")
                assert len(active.turns) == 1
                running = active.turns[0].lifecycle
                assert running.status == "running" and running.finished_at is None
                assert running.run_id is not None
                assert before <= running.started_at <= datetime.now(UTC)
                assert running.started_at.tzinfo is UTC
                assert active.last_turn is None and active.messages == ()
                assert len(active.artifacts) == 1
                assert active.artifacts[0].run_id == running.run_id
                with pytest.raises(FrozenInstanceError):
                    setattr(running, "status", "completed")
                with pytest.raises(SessionNotFoundError):
                    registry.read(created.session_id, owner="bob")
                with pytest.raises(SessionNotFoundError):
                    await registry.execute_turn(created.session_id, owner="bob", agent=agent, prompt="unauthorized")
                with pytest.raises(ConversationBusyError):
                    await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="overlap")
                assert registry.read(created.session_id, owner="alice").turns == active.turns
                assert registry.read(other.session_id, owner="bob").turns == ()
                if outcome == "cancelled":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    if outcome == "failed":
                        with pytest.raises(RuntimeError) as caught:
                            await asyncio.wait_for(task, timeout=5)
                        assert caught.value is failure
                    else:
                        result = await asyncio.wait_for(task, timeout=5)
                        assert result.run_id == running.run_id
            finally:
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            settled = registry.read(created.session_id, owner="alice")
            entry, = settled.turns
            record = entry.lifecycle
            assert record.status == outcome and record.run_id == running.run_id
            assert record.started_at == running.started_at
            assert record.finished_at is not None and record.finished_at.tzinfo is UTC
            assert record.started_at <= record.finished_at <= datetime.now(UTC)
            assert running.status == "running" and running.finished_at is None
            assert settled.last_turn is not None and settled.last_turn.run_id == record.run_id
            assert settled.messages and settled.artifacts == active.artifacts
            followup_task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="followup",
            ))
            try:
                await asyncio.wait_for(followup_started.wait(), timeout=5)
                during_followup = registry.read(created.session_id, owner="alice")
                assert during_followup.messages == settled.messages
                assert during_followup.last_turn == settled.last_turn
                assert during_followup.turns[0].lifecycle == record
                assert during_followup.turns[1].lifecycle.status == "running"
                assert during_followup.turns[1].lifecycle.run_id is not None
                assert during_followup.turns[1].lifecycle.run_id != record.run_id
                followup_release.set()
                followup = await asyncio.wait_for(followup_task, timeout=5)
            finally:
                if not followup_task.done():
                    followup_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await followup_task
            final = registry.read(created.session_id, owner="alice")
            assert final.turns[0].lifecycle == record
            assert final.turns[0].observation is None
            assert len(final.turns) == 2 and final.turns[1].lifecycle.status == "completed"
            assert final.turns[1].lifecycle.run_id == followup.run_id != record.run_id
            assert final.last_turn is final.turns[1].observation
            assert settled.last_turn is entry.observation and entry.observation is not None
            assert settled.messages == tuple(entry.observation.messages)
            assert final.artifacts == settled.artifacts

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_setup_lifecycle_without_run_id_preserves_prior_history(outcome: str) -> None:
    registry = AgentSessionRegistry()
    created = registry.create(owner="alice", initial_context={"recipe": 42})

    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        class UnavailableTools(FunctionToolset[None]):
            async def for_run(self, ctx: RunContext[None]) -> FunctionToolset[None]:
                started.set()
                await release.wait()
                raise RuntimeError("Toolset unavailable")

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Hello.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="first")
            prior = registry.read(created.session_id, owner="alice")
            task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="invalid", toolsets=[UnavailableTools()],
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                active = registry.read(created.session_id, owner="alice")
                assert active.turns[:-1] == prior.turns
                assert active.messages == prior.messages and active.last_turn == prior.last_turn
                assert active.turns[-1].lifecycle.status == "running" and active.turns[-1].lifecycle.run_id is None
                assert active.turns[-1].lifecycle.finished_at is None
                if outcome == "cancelled":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    release.set()
                    with pytest.raises(RuntimeError, match="Toolset unavailable"):
                        await asyncio.wait_for(task, timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
            settled = registry.read(created.session_id, owner="alice")
            assert settled.messages == prior.messages and settled.last_turn == prior.last_turn
            assert settled.turns[:-1] == prior.turns
            assert settled.turns[-1].lifecycle.run_id is None and settled.turns[-1].lifecycle.status == outcome
            assert settled.turns[-1].lifecycle.started_at == active.turns[-1].lifecycle.started_at
            assert settled.turns[-1].lifecycle.finished_at is not None
            release.set()
            with pytest.raises(RuntimeError, match="Toolset unavailable"):
                await registry.execute_turn(
                    created.session_id, owner="alice", agent=agent, prompt="invalid again",
                    toolsets=[UnavailableTools()],
                )
            repeated = registry.read(created.session_id, owner="alice")
            assert repeated.messages == prior.messages and repeated.last_turn == prior.last_turn
            assert repeated.turns[:-1] == settled.turns
            assert repeated.turns[-1].lifecycle.status == "failed" and repeated.turns[-1].lifecycle.run_id is None
            await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="followup")
            final = registry.read(created.session_id, owner="alice")
            assert len(final.turns) == 4 and final.turns[-1].lifecycle.status == "completed"
            prompts = [part.content for message in final.messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            assert "invalid" not in prompts and "invalid again" not in prompts and prompts[-1] == "followup"

    asyncio.run(exercise())
