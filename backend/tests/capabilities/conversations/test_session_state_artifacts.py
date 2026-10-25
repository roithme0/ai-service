import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue
from pydantic_ai import Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.artifacts import ArtifactAccepted, ArtifactCapability
from app.capabilities.conversations.session_state import SessionState, SessionBusyError
from app.capabilities.conversations.turns import create_turn_agent


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def capability(name: str = "example") -> ArtifactCapability:
    return ArtifactCapability(
        type=name, description="Present a name.",
        payloadSchema={"type": "object", "properties": {"name": {"type": "string"}},
                       "required": ["name"], "additionalProperties": False},
    )


def arguments(name: str, artifact_type: str = "example") -> dict[str, JsonValue]:
    return {"type": artifact_type, "content": {"title": name, "payload": {"name": name}}}


def returns(messages: Sequence[ModelMessage]) -> list[ToolReturnPart]:
    return [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]


def prompt(messages: Sequence[ModelMessage]) -> str:
    values = [part.content for message in messages for part in message.parts
              if isinstance(part, UserPromptPart) and isinstance(part.content, str)]
    return values[-1]


def test_owned_publication_snapshots_capabilities_and_artifacts_and_continues_without_replay() -> None:
    advertised = capability()
    capabilities = [advertised]
    session_state = SessionState(artifact_capabilities=capabilities)
    advertised.payload_schema.clear()
    advertised.payload_schema["type"] = "null"
    capabilities.clear()
    before = datetime.now(UTC)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert [tool.name for tool in info.function_tools] == ["present_artifact"]
        if not returns(messages):
            return ModelResponse(parts=[ToolCallPart("present_artifact", arguments("First"), "first"),
                                        ToolCallPart("present_artifact", arguments("Second"), "second")])
        artifacts = session_state.artifacts
        assert [item.content.title for item in artifacts] == ["First", "Second"]
        for result, artifact in zip(returns(messages), artifacts, strict=True):
            assert result.content == ArtifactAccepted(artifact_id=artifact.artifact_id)
        return ModelResponse(parts=[TextPart("Presented.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            first = await session_state.execute_turn(agent, "present")
            snapshot = session_state.artifacts
            payload = snapshot[0].content.payload
            assert isinstance(payload, dict)
            payload["name"] = "changed"
            second = await session_state.execute_turn(agent, "followup")
        artifacts = session_state.artifacts
        assert [item.content.payload for item in artifacts] == [{"name": "First"}, {"name": "Second"}]
        assert [item.tool_call_id for item in artifacts] == ["first", "second"]
        assert {item.run_id for item in artifacts} == {first.run_id}
        assert len({item.artifact_id for item in artifacts}) == 2
        assert all(before <= item.created_at <= datetime.now(UTC) for item in artifacts)
        assert second.usage.tool_calls == first.usage.tool_calls
        assert len(returns(session_state.messages)) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("limit", [0, 2])
def test_capacity_is_shared_across_turns_and_rejections_do_not_publish(limit: int) -> None:
    session_state = SessionState(artifact_capabilities=[capability()], max_artifacts=limit)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        label = prompt(messages)
        if not any(result.tool_call_id == label for result in returns(messages)):
            return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(label), label)])
        result = returns(messages)[-1]
        if label == "third" or limit == 0:
            assert result.outcome == "failed"
            assert "artifact_limit" in str(result.content)
        else:
            assert result.outcome == "success"
        assert len(session_state.artifacts) <= limit
        return ModelResponse(parts=[TextPart("Done.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            first = await session_state.execute_turn(agent, "first")
            second = await session_state.execute_turn(agent, "second")
            await session_state.execute_turn(agent, "third")
        assert len(session_state.artifacts) == limit
        if limit:
            assert [item.run_id for item in session_state.artifacts] == [first.run_id, second.run_id]

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["model", "tool", "cancel"])
def test_publication_survives_later_failure_or_cancellation_and_is_visible_during_execution(failure: str) -> None:
    async def exercise() -> None:
        published = asyncio.Event()
        session_state = SessionState(artifact_capabilities=[capability()], max_artifacts=1)

        def fail() -> str:
            """Attempt another operation."""
            raise RuntimeError("Tool failed after publication")

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if prompt(messages) == "followup":
                accepted_returns = [part for part in returns(messages) if part.tool_name == "present_artifact"]
                assert len(accepted_returns) == 1
                assert accepted_returns[0].outcome == "success"
                assert len(session_state.artifacts) == 1
                return ModelResponse(parts=[TextPart("Already presented.")])
            if not returns(messages):
                return ModelResponse(parts=[ToolCallPart("present_artifact", arguments("Retained"), "publish")])
            published.set()
            if failure == "tool":
                return ModelResponse(parts=[ToolCallPart("fail", {}, "fail")])
            if failure == "cancel":
                await asyncio.Event().wait()
            raise RuntimeError("Model failed after publication")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(fail)])
        async with agent:
            task = asyncio.create_task(session_state.execute_turn(agent, "present"))
            try:
                await asyncio.wait_for(published.wait(), timeout=5)
                accepted = session_state.artifacts
                assert len(accepted) == 1
                if failure == "cancel":
                    with pytest.raises(SessionBusyError):
                        await session_state.execute_turn(agent, "busy")
            finally:
                if failure == "cancel":
                    task.cancel()
                with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
                    await task
            failed = session_state.conversation
            assert failed is not None
            assert accepted[0].run_id == session_state.turn_executions[-1].lifecycle.run_id
            result = await session_state.execute_turn(agent, "followup")
        assert result.usage.tool_calls == failed.usage.tool_calls
        assert session_state.artifacts == accepted

    asyncio.run(exercise())


def test_shared_agent_keeps_concurrent_capabilities_and_publications_isolated() -> None:
    async def exercise() -> None:
        both_started = asyncio.Event()
        started: set[str] = set()
        session_states = {name: SessionState(artifact_capabilities=[capability(name)], max_artifacts=1)
                         for name in ("left", "right")}

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            label = prompt(messages)
            assert label in (info.instructions or "")
            if not returns(messages):
                started.add(label)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=5)
                return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(label, label), "same-call-id")])
            assert session_states[label].artifacts[0].content.title == label
            return ModelResponse(parts=[TextPart(label)])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        async with agent:
            left, right = await asyncio.gather(*(item.execute_turn(agent, name) for name, item in session_states.items()))
            empty = SessionState()

            def without_artifacts(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                assert info.function_tools == []
                return ModelResponse(parts=[TextPart("No presentation configured.")])

            with agent.override(model=FunctionModel(without_artifacts)):
                await empty.execute_turn(agent, "empty")
        assert empty.artifacts == ()
        assert session_states["left"].artifacts[0].run_id == left.run_id
        assert session_states["right"].artifacts[0].run_id == right.run_id
        assert session_states["left"].artifacts[0].artifact_id != session_states["right"].artifacts[0].artifact_id

    asyncio.run(exercise())


def test_invalid_artifact_configuration_is_rejected_at_creation() -> None:
    with pytest.raises(ValueError, match="unique"):
        SessionState(artifact_capabilities=[capability(), capability()])
    with pytest.raises(ValueError, match="non-negative"):
        SessionState(max_artifacts=-1)
