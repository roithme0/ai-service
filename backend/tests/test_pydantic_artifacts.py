import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import JsonValue
from pydantic_ai import UnexpectedModelBehavior, models
from pydantic_ai.messages import (
    ModelMessage, ModelMessagesTypeAdapter, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agentic.artifacts import (
    ArtifactAccepted, ArtifactRejected, ArtifactSubmission, create_artifact_toolset,
)
from app.agentic.observation import TurnObservation
from app.agentic.turns import create_turn_agent, execute_turn
from app.sessions.models.artifacts import ArtifactCapability, ArtifactPayload, PublishedArtifact


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def capability(*, metadata: bool = False) -> ArtifactCapability:
    return ArtifactCapability(
        type="example", description="Show a name.", titleDescription="Use the name as the title.",
        payloadSchema={"$defs": {"name": {"type": "string"}}, "type": "object",
                       "properties": {"name": {"$ref": "#/$defs/name"}},
                       "required": ["name"], "additionalProperties": False},
        metadataSchema={"type": "object", "properties": {"reference": {"type": "string", "format": "uuid"}},
                        "required": ["reference"], "additionalProperties": False} if metadata else None,
    )


def arguments(name: str = "Oats", *, changes: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
    updates = changes or {}
    payload: dict[str, JsonValue] = {"title": name, "subtitle": "Brand", "payload": {"name": name}}
    payload.update({key: value for key, value in updates.items() if key != "type"})
    return {"candidate": {"type": updates.get("type", "example"), "payload": payload}}


def returns(messages: list[ModelMessage]) -> list[ToolReturnPart]:
    return [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]


@dataclass
class MemoryAcceptance:
    owner: str
    limit: int = 2
    artifacts: list[PublishedArtifact[ArtifactPayload]] = field(default_factory=list)
    submissions: list[ArtifactSubmission] = field(default_factory=list)

    def __call__(self, submission: ArtifactSubmission, /) -> ArtifactAccepted | ArtifactRejected:
        self.submissions.append(submission)
        if len(self.artifacts) >= self.limit:
            return ArtifactRejected(reason="artifact_limit")
        artifact_id = f"{self.owner}-{len(self.artifacts) + 1}"
        self.artifacts.append(PublishedArtifact(
            artifact_id=artifact_id, type=submission.candidate.type, created_at=datetime.now(UTC),
            turn_id=submission.run_id, payload=submission.candidate.payload.model_copy(deep=True),
            order=len(self.artifacts),
        ))
        return ArtifactAccepted(artifact_id=artifact_id)


def test_publications_are_accepted_in_order_before_model_continues_and_survive_failure() -> None:
    acceptance = MemoryAcceptance("session")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not returns(messages):
            definition = next(tool for tool in info.function_tools if tool.name == "present_artifact")
            schema = definition.parameters_json_schema
            reference = schema["properties"]["candidate"]["$ref"]
            assert schema["$defs"][reference.rsplit("/", 1)[-1]]["properties"]["type"]["enum"] == ["example"]
            assert definition.sequential
            assert "Use the name as the title" in str(info.instructions)
            return ModelResponse(parts=[ToolCallPart("present_artifact", arguments("First"), "first"),
                                        ToolCallPart("present_artifact", arguments("Second"), "second")])
        assert [artifact.payload.title for artifact in acceptance.artifacts] == ["First", "Second"]
        for result, artifact in zip(returns(messages), acceptance.artifacts, strict=True):
            assert result.outcome == "success"
            assert result.content == ArtifactAccepted(artifact_id=artifact.artifact_id)
        raise RuntimeError("Model failed after publication")

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        observation = TurnObservation()
        async with agent:
            with pytest.raises(RuntimeError, match="after publication"):
                await execute_turn(agent, "Present two items.", observation=observation,
                                   toolsets=[create_artifact_toolset([capability()], acceptance)])
            def followup(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                assert info.function_tools == []
                assert [part.content for part in returns(messages)] == [
                    {"kind": "presented", "artifact_id": artifact.artifact_id} for artifact in acceptance.artifacts
                ]
                return ModelResponse(parts=[TextPart("Both artifacts were accepted.")])

            history = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(observation.messages))
            with agent.override(model=FunctionModel(followup)):
                result = await execute_turn(agent, "What was accepted?", message_history=history)
            assert result.usage.tool_calls == 0
        assert len(acceptance.artifacts) == 2
        assert [item.order for item in acceptance.artifacts] == [0, 1]
        assert [item.tool_call_id for item in acceptance.submissions] == ["first", "second"]
        assert all(item.run_id == observation.run_id for item in acceptance.submissions)
        assert len(returns(observation.messages)) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(("changes", "metadata", "reason"), [
    ({"type": "missing"}, False, "unsupported_type"),
    ({"payload": {"name": 1}}, False, "invalid_payload"),
    ({"payload": {"name": "x", "extra": True}}, False, "invalid_payload"),
    ({"metadata": {}}, False, "invalid_metadata"),
    ({}, True, "invalid_metadata"),
    ({"metadata": {"reference": "not-a-uuid"}}, True, "invalid_metadata"),
])
def test_schema_rejections_are_native_failed_results_without_acceptance(
    changes: dict[str, JsonValue], metadata: bool, reason: str,
) -> None:
    acceptance = MemoryAcceptance("session")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not returns(messages):
            return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(changes=changes), "call")])
        result, = returns(messages)
        assert result.outcome == "failed"
        assert reason in str(result.content)
        return ModelResponse(parts=[TextPart("The artifact was rejected.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        result = await execute_turn(agent, "Present it.", toolsets=[
            create_artifact_toolset([capability(metadata=metadata)], acceptance),
        ])
        assert result.output == "The artifact was rejected."
        assert acceptance.submissions == []
        assert acceptance.artifacts == []

    asyncio.run(exercise())


@pytest.mark.parametrize("changes", [{"title": " "}, {"subtitle": " "}, {"title": 1}, {"extra": True},
                                     {"payload": float("nan")}, {"payload": {"name": float("inf")}},
                                     {"metadata": {"value": float("-inf")}}])
def test_native_argument_validation_prevents_acceptance(changes: dict[str, JsonValue]) -> None:
    acceptance = MemoryAcceptance("session")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(changes=changes), "call")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        with pytest.raises(UnexpectedModelBehavior):
            await execute_turn(agent, "Present it.", toolsets=[create_artifact_toolset([capability()], acceptance)])
        assert acceptance.submissions == []

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid", [
    {"type": "example", "title": "Oats", "payload": {"name": "Oats"}},
    {"candidate": {"type": "example", "extra": True,
                   "payload": {"title": "Oats", "payload": {"name": "Oats"}}}},
])
def test_tool_requires_candidate_shape_without_unknown_candidate_fields(invalid: dict[str, JsonValue]) -> None:
    acceptance = MemoryAcceptance("session")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("present_artifact", invalid, "call")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        with pytest.raises(UnexpectedModelBehavior):
            await execute_turn(agent, "Present it.", toolsets=[create_artifact_toolset([capability()], acceptance)])
        assert acceptance.submissions == []

    asyncio.run(exercise())


def test_capacity_rejection_preserves_previous_artifact_and_reports_failure() -> None:
    acceptance = MemoryAcceptance("session", limit=1)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not returns(messages):
            return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(), "first"),
                                        ToolCallPart("present_artifact", arguments("Second"), "second")])
        first, second = returns(messages)
        assert first.outcome == "success"
        assert second.outcome == "failed"
        assert "artifact_limit" in str(second.content)
        return ModelResponse(parts=[TextPart("One artifact was accepted.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        await execute_turn(agent, "Present two.", toolsets=[create_artifact_toolset([capability()], acceptance)])
        assert len(acceptance.artifacts) == 1
        assert len(acceptance.submissions) == 2

    asyncio.run(exercise())


def test_concurrent_runs_on_shared_agent_isolate_capabilities_acceptance_and_retained_data() -> None:
    async def exercise() -> None:
        both_started = asyncio.Event()
        started: set[str] = set()
        left, right = MemoryAcceptance("left"), MemoryAcceptance("right")
        left_capability, right_capability = capability(), capability(metadata=True)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompt = next(part.content for msg in messages for part in msg.parts if isinstance(part, UserPromptPart))
            assert isinstance(prompt, str)
            if not returns(messages):
                started.add(prompt)
                if len(started) == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=5)
                args = arguments(prompt, changes={
                    "metadata": {"reference": "00000000-0000-4000-8000-000000000001"},
                } if prompt == "right" else None)
                return ModelResponse(parts=[ToolCallPart("present_artifact", args, prompt)])
            assert returns(messages)[0].content == ArtifactAccepted(artifact_id=f"{prompt}-1")
            return ModelResponse(parts=[TextPart(prompt)])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        left_tools = create_artifact_toolset([left_capability], left)
        left_capability.payload_schema.clear()
        async with agent:
            results = await asyncio.gather(
                execute_turn(agent, "left", toolsets=[left_tools]),
                execute_turn(agent, "right", toolsets=[create_artifact_toolset([right_capability], right)]),
            )
        assert [item.payload.title for item in left.artifacts] == ["left"]
        assert [item.payload.title for item in right.artifacts] == ["right"]
        assert left.artifacts[0].payload.metadata is None
        assert right.artifacts[0].payload.metadata is not None
        assert right.artifacts[0].payload.subtitle == "Brand"
        assert right.artifacts[0].payload.metadata == {"reference": "00000000-0000-4000-8000-000000000001"}
        assert left.artifacts[0].turn_id != right.artifacts[0].turn_id
        left_request = left.submissions[0].candidate.payload.payload
        assert isinstance(left_request, dict)
        left_request["name"] = "Changed after acceptance"
        assert left.artifacts[0].payload.payload == {"name": "left"}
        assert all(result.usage.tool_calls == 1 for result in results)

    asyncio.run(exercise())


def test_accepted_artifact_survives_cancellation_during_next_model_request() -> None:
    async def exercise() -> None:
        acceptance = MemoryAcceptance("session")
        continuing = asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if not returns(messages):
                return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(), "call")])
            assert len(acceptance.artifacts) == 1
            continuing.set()
            await asyncio.Event().wait()
            return ModelResponse(parts=[TextPart("Unreachable")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        observation = TurnObservation()
        async with agent:
            task = asyncio.create_task(execute_turn(agent, "Present it.", observation=observation,
                toolsets=[create_artifact_toolset([capability()], acceptance)]))
            await asyncio.wait_for(continuing.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert len(acceptance.artifacts) == 1
        assert returns(observation.messages)[0].outcome == "success"

    asyncio.run(exercise())


def test_unexpected_acceptance_error_aborts_without_fabricating_success() -> None:
    calls = 0

    def accept(submission: ArtifactSubmission) -> ArtifactAccepted | ArtifactRejected:
        nonlocal calls
        calls += 1
        raise RuntimeError("Acceptance unavailable")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("present_artifact", arguments(), "call")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        observation = TurnObservation()
        with pytest.raises(RuntimeError, match="Acceptance unavailable"):
            await execute_turn(agent, "Present it.", observation=observation,
                               toolsets=[create_artifact_toolset([capability()], accept)])
        assert calls == 1
        assert returns(observation.messages) == []

    asyncio.run(exercise())


def test_empty_capabilities_offer_no_tool_and_duplicate_types_are_rejected() -> None:
    acceptance = MemoryAcceptance("session")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.function_tools == []
        return ModelResponse(parts=[TextPart("Text only.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        await execute_turn(agent, "Help.", toolsets=[create_artifact_toolset([], acceptance)])
        with pytest.raises(ValueError, match="unique"):
            create_artifact_toolset([capability(), capability()], acceptance)

    asyncio.run(exercise())
