import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import RunContext, Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextContent, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset

from app.agentic.artifacts import ArtifactAccepted
from app.agentic.conversations import ConversationBusyError
from app.agentic.sessions import AgentSessionRegistry, SessionNotFoundError
from app.agentic.turns import create_turn_agent
from app.sessions.models.artifacts import ArtifactCapability


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 20, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_owner_checks_isolation_and_detached_snapshots() -> None:
    clock = Clock()
    registry = AgentSessionRegistry(clock=clock)
    first = registry.create(owner="alice", initial_context={"recipe": 42})
    second = registry.create(owner="bob")
    assert first.session_id != second.session_id
    assert first.expires_at == clock.now + timedelta(minutes=90)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts = [part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart)]
        return ModelResponse(parts=[TextPart(str(prompts))])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            for session_id in (first.session_id, "missing"):
                with pytest.raises(SessionNotFoundError, match="^Session not found\\.$"):
                    registry.read(session_id, owner="bob")
                with pytest.raises(SessionNotFoundError, match="^Session not found\\.$"):
                    await registry.execute_turn(session_id, owner="bob", agent=agent, prompt="unauthorized")
            result = await registry.execute_turn(first.session_id, owner="alice", agent=agent, prompt="hello")
            assert "recipe" in result.output and "hello" in result.output
            assert "unauthorized" not in result.output
            snapshot = registry.read(first.session_id, owner="alice")
            snapshot.messages[0].parts.clear()
            assert snapshot.last_turn is not None
            snapshot.last_turn.messages.clear()
            assert snapshot.messages == ()
            assert snapshot.last_turn is snapshot.turns[-1].observation
            fresh = registry.read(first.session_id, owner="alice")
            assert fresh.messages[0].parts and fresh.last_turn is not None and fresh.last_turn.messages
            reply = await registry.execute_turn(first.session_id, owner="alice", agent=agent, prompt="followup")
            assert "hello" in reply.output and "followup" in reply.output
            other = await registry.execute_turn(second.session_id, owner="bob", agent=agent, prompt="independent")
            assert "recipe" not in other.output and "hello" not in other.output
            assert other.conversation_id != reply.conversation_id
        assert registry.read(first.session_id, owner="alice").expires_at == first.expires_at

    asyncio.run(exercise())


def test_snapshot_initial_context_survives_setup_failure_and_is_replaced_by_history() -> None:
    registry = AgentSessionRegistry()
    created = registry.create(owner="alice", initial_context={"recipe": 42})
    seed = registry.read(created.session_id, owner="alice")
    assert seed.initial_context_message is not None and seed.last_turn is None
    assert seed.messages == (seed.initial_context_message,) and seed.turns == ()
    seed.messages[0].parts.clear()
    pristine = registry.read(created.session_id, owner="alice")
    assert pristine.messages[0].parts

    class UnavailableTools(FunctionToolset[None]):
        async def for_run(self, ctx: RunContext[None]) -> FunctionToolset[None]:
            raise RuntimeError("Toolset unavailable")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts = [part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart)]
        assert len(prompts) == 2 and not isinstance(prompts[0], str)
        assert isinstance(prompts[0][0], TextContent) and '"recipe":42' in prompts[0][0].content
        return ModelResponse(parts=[TextPart("Hello.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            with pytest.raises(RuntimeError, match="Toolset unavailable"):
                await registry.execute_turn(
                    created.session_id, owner="alice", agent=agent, prompt="invalid", toolsets=[UnavailableTools()],
                )
            failed = registry.read(created.session_id, owner="alice")
            assert failed.last_turn is None and failed.messages == pristine.messages
            assert failed.turns[0].observation is None
            await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="hello")
            settled = registry.read(created.session_id, owner="alice")
            assert settled.initial_context_message is None
            assert settled.last_turn is settled.turns[-1].observation
            observation = settled.turns[-1].observation
            assert observation is not None and settled.messages == tuple(observation.messages)
            observation.messages.clear()
            assert settled.messages == ()
            assert registry.read(created.session_id, owner="alice").messages
            assert failed.messages == pristine.messages and failed.last_turn is None

    asyncio.run(exercise())


def test_exact_expiry_denies_reads_and_execution_without_refreshing_lifetime() -> None:
    clock = Clock()
    registry = AgentSessionRegistry(clock=clock)
    created = registry.create(owner="alice")
    clock.now = created.expires_at - timedelta(microseconds=1)
    assert registry.read(created.session_id, owner="alice").expires_at == created.expires_at
    clock.now = created.expires_at
    calls: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("model")
        return ModelResponse(parts=[TextPart("Unexpected")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        with pytest.raises(SessionNotFoundError):
            registry.read(created.session_id, owner="alice")
        with pytest.raises(SessionNotFoundError):
            await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="late")
        assert not calls
        replacement = registry.create(owner="alice")
        assert replacement.session_id != created.session_id
        assert replacement.expires_at == clock.now + timedelta(minutes=90)

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_admitted_turn_survives_expiry_and_retains_native_settlement(outcome: str) -> None:
    clock = Clock()
    registry = AgentSessionRegistry(clock=clock)
    created = registry.create(owner="alice", artifact_capabilities=[ArtifactCapability(
        type="example", description="Present data.", payloadSchema={"type": "object"},
    )])

    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        operations: list[str] = []

        async def operation() -> str:
            """Perform a domain operation."""
            operations.append("started")
            started.set()
            await release.wait()
            operations.append("finished")
            return "Done"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
            if not returns:
                return ModelResponse(parts=[
                    ToolCallPart("present_artifact", {"candidate": {
                        "type": "example", "payload": {"title": "Before", "payload": {}},
                    }}, "before"),
                    ToolCallPart("operation", {}, "operation"),
                ])
            if len(returns) == 2:
                return ModelResponse(parts=[ToolCallPart("present_artifact", {"candidate": {
                    "type": "example", "payload": {"title": "After", "payload": {}},
                }}, "after")])
            assert [part.tool_call_id for part in returns] == ["before", "operation", "after"]
            assert isinstance(returns[-1].content, ArtifactAccepted)
            if outcome == "failure":
                raise RuntimeError("Later model failure")
            return ModelResponse(parts=[TextPart("Finished after expiry.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(operation)])
        async with agent:
            task = asyncio.create_task(registry.execute_turn(
                created.session_id, owner="alice", agent=agent, prompt="work",
            ))
            await asyncio.wait_for(started.wait(), timeout=5)
            before = registry.read(created.session_id, owner="alice")
            assert len(before.artifacts) == 1
            before.artifacts[0].payload.payload["injected"] = True
            assert registry.read(created.session_id, owner="alice").artifacts[0].payload.payload == {}
            with pytest.raises(ConversationBusyError):
                await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="overlap")
            clock.now = created.expires_at
            with pytest.raises(SessionNotFoundError):
                registry.read(created.session_id, owner="alice")
            with pytest.raises(SessionNotFoundError):
                await registry.execute_turn(created.session_id, owner="alice", agent=agent, prompt="late")
            assert not task.done()
            if outcome == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert operations == ["started"]
            else:
                release.set()
                if outcome == "failure":
                    with pytest.raises(RuntimeError, match="Later model failure"):
                        await asyncio.wait_for(task, timeout=5)
                else:
                    result = await asyncio.wait_for(task, timeout=5)
                    assert result.output == "Finished after expiry."
                assert operations == ["started", "finished"]
            with pytest.raises(SessionNotFoundError):
                registry.read(created.session_id, owner="alice")

    asyncio.run(exercise())


def test_session_creation_rejects_invalid_lifetime_owner_and_clock() -> None:
    for lifetime in (timedelta(), timedelta(seconds=-1)):
        with pytest.raises(ValueError, match="positive"):
            AgentSessionRegistry(lifetime=lifetime)
    registry = AgentSessionRegistry(clock=Clock())
    with pytest.raises(ValueError, match="owner"):
        registry.create(owner=" ")
    naive_clock = Clock(datetime(2026, 10, 20))
    with pytest.raises(ValueError, match="timezone-aware"):
        AgentSessionRegistry(clock=naive_clock).create(owner="alice")
