import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from pydantic_ai import RunContext, Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agentic.session_state import SessionBusyError
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
        assert registry.read(created.session_id, owner="alice").turn_executions == ()
        async with agent:
            task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="work",
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                active = registry.read(created.session_id, owner="alice")
                assert len(active.turn_executions) == 1
                running = active.turn_executions[0].lifecycle
                assert running.status == "running" and running.finished_at is None
                assert running.run_id is not None
                assert before <= running.started_at <= datetime.now(UTC)
                assert running.started_at.tzinfo is UTC
                assert active.conversation.messages == [] and active.messages
                assert len(active.artifacts) == 1
                assert active.artifacts[0].run_id == running.run_id
                with pytest.raises(FrozenInstanceError):
                    setattr(running, "status", "completed")
                with pytest.raises(SessionNotFoundError):
                    registry.read(created.session_id, owner="bob")
                with pytest.raises(SessionNotFoundError):
                    await registry.execute_turn(created.session_id, owner="bob", agent=agent, prompt="unauthorized")
                with pytest.raises(SessionBusyError):
                    await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="overlap")
                assert registry.read(created.session_id, owner="alice").turn_executions == active.turn_executions
                assert registry.read(other.session_id, owner="bob").turn_executions == ()
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
            entry, = settled.turn_executions
            record = entry.lifecycle
            assert record.status == outcome and record.run_id == running.run_id
            assert record.started_at == running.started_at
            assert record.finished_at is not None and record.finished_at.tzinfo is UTC
            assert record.started_at <= record.finished_at <= datetime.now(UTC)
            assert running.status == "running" and running.finished_at is None
            assert entry.observation is None and settled.conversation.messages[-1].run_id == record.run_id
            assert settled.messages and settled.artifacts == active.artifacts
            followup_task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="followup",
            ))
            try:
                await asyncio.wait_for(followup_started.wait(), timeout=5)
                during_followup = registry.read(created.session_id, owner="alice")
                assert during_followup.conversation == settled.conversation
                assert len(during_followup.messages) >= len(settled.messages)
                assert during_followup.turn_executions[0].lifecycle == record
                assert during_followup.turn_executions[1].lifecycle.status == "running"
                assert during_followup.turn_executions[1].lifecycle.run_id is not None
                assert during_followup.turn_executions[1].lifecycle.run_id != record.run_id
                followup_release.set()
                followup = await asyncio.wait_for(followup_task, timeout=5)
            finally:
                if not followup_task.done():
                    followup_task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await followup_task
            final = registry.read(created.session_id, owner="alice")
            assert final.turn_executions[0].lifecycle == record
            assert final.turn_executions[0].observation is None
            assert len(final.turn_executions) == 2 and final.turn_executions[1].lifecycle.status == "completed"
            assert final.turn_executions[1].lifecycle.run_id == followup.run_id != record.run_id
            assert all(execution.observation is None for execution in final.turn_executions)
            assert settled.messages == tuple(settled.conversation.messages)
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
                assert active.turn_executions[:-1] == prior.turn_executions
                assert active.messages == prior.messages and active.conversation == prior.conversation
                assert active.turn_executions[-1].lifecycle.status == "running" and active.turn_executions[-1].lifecycle.run_id is None
                assert active.turn_executions[-1].lifecycle.finished_at is None
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
            assert settled.messages == prior.messages and settled.conversation == prior.conversation
            assert settled.turn_executions[:-1] == prior.turn_executions
            assert settled.turn_executions[-1].lifecycle.run_id is None and settled.turn_executions[-1].lifecycle.status == outcome
            assert settled.turn_executions[-1].lifecycle.started_at == active.turn_executions[-1].lifecycle.started_at
            assert settled.turn_executions[-1].lifecycle.finished_at is not None
            release.set()
            with pytest.raises(RuntimeError, match="Toolset unavailable"):
                await registry.execute_turn(
                    created.session_id, owner="alice", agent=agent, prompt="invalid again",
                    toolsets=[UnavailableTools()],
                )
            repeated = registry.read(created.session_id, owner="alice")
            assert repeated.messages == prior.messages and repeated.conversation == prior.conversation
            assert repeated.turn_executions[:-1] == settled.turn_executions
            assert repeated.turn_executions[-1].lifecycle.status == "failed" and repeated.turn_executions[-1].lifecycle.run_id is None
            await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="followup")
            final = registry.read(created.session_id, owner="alice")
            assert len(final.turn_executions) == 4 and final.turn_executions[-1].lifecycle.status == "completed"
            prompts = [part.content for message in final.messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            assert "invalid" not in prompts and "invalid again" not in prompts and prompts[-1] == "followup"

    asyncio.run(exercise())
