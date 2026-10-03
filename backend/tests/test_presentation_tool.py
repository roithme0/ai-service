import asyncio
import json
from typing import Never

import pytest
from pydantic import JsonValue

from app.sessions.artifacts import ArtifactCandidate
from app.sessions.agent_service import AgentInputAccepted
from app.sessions.context import SessionContext, validate_context_input
from app.sessions.conversation import ConversationSessionSettings, ConversationTurnReservation
from app.sessions.model_sessions import ModelSessionStore, create_model_agent, new_model_session_store
from app.sessions.presentation import PresentationPayload, presentation_tool_source
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation, ToolRegistry
from app.sessions.text_sessions import TextSessionCreation
from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall


CAPABILITY = {"type": "example", "description": "An arbitrary consumer presentation",
              "titleDescription": "Use the retrieved foodstuff name as the title.",
              "subtitleDescription": "Use the brand as the subtitle; omit it when there is no brand.",
              "payloadSchema": {"$defs": {"name": {"type": "string"}}, "type": "object",
                                "properties": {"name": {"$ref": "#/$defs/name"}},
                                "required": ["name"], "additionalProperties": False}}


def tool_for_session(metadata_schema: dict[str, JsonValue] | None = None) -> tuple[
    RegisteredTool[ArtifactCandidate[PresentationPayload]], ModelSessionStore, str,
    ConversationTurnReservation[SessionContext, PresentationPayload],
]:
    capability = {**CAPABILITY, **({"metadataSchema": metadata_schema} if metadata_schema is not None else {})}
    accepted = validate_context_input({"context": {}, "artifactCapabilities": [capability]})
    assert isinstance(accepted, AgentInputAccepted)
    store = new_model_session_store()
    session = store.create(accepted.context, ConversationSessionSettings(max_artifacts=1))
    store.append_user_message(session.session_id, "Present")
    reservation = store.reserve_turn(session.session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    source = presentation_tool_source(accepted.context.artifact_capabilities)
    return source.registered_tools()[0], store, session.session_id, reservation


@pytest.mark.parametrize("arguments", ["null", "{", '{"type":"example","title":" ","payload":{"name":"Oats"}}',
    '{"type":"example","title":"Data","payload":{"name":NaN}}',
    '{"type":"example","title":"Data","payload":{"name":"Oats"},"extra":true}'])
def test_invalid_arguments_do_not_create_an_artifact_candidate(arguments: str) -> None:
    tool, store, session_id, reservation = tool_for_session()
    async def exercise() -> None:
        result = await ToolRegistry((tool,)).invoke(tool.name, arguments)
        assert json.loads(output_text(result))["kind"] == "rejected"
        assert result.artifact is None
    asyncio.run(exercise())

    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts == ()


METADATA_SCHEMA: dict[str, JsonValue] = {
    "type": "object", "properties": {"reference": {"type": "string", "format": "uuid"}},
    "required": ["reference"], "additionalProperties": False,
}


@pytest.mark.parametrize("metadata", [None, {}, {"reference": "invalid"}, {"reference": 123},
    {"reference": "00000000-0000-4000-8000-000000000001", "extra": True}])
def test_invalid_metadata_is_rejected_without_candidate(metadata: JsonValue) -> None:
    tool, store, session_id, reservation = tool_for_session(METADATA_SCHEMA)
    result = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, json.dumps({
        "type": "example", "title": "Data", "payload": {"name": "Oats"}, "metadata": metadata,
    })))
    assert json.loads(output_text(result))["reason"] in {"invalid_metadata", "invalid_arguments"}
    assert store.complete_turn(session_id, reservation, "completed", "Finished").artifacts == ()


def test_metadata_is_validated_and_retained_separately_from_display_data() -> None:
    tool, store, session_id, reservation = tool_for_session(METADATA_SCHEMA)
    metadata = {"reference": "00000000-0000-4000-8000-000000000001"}
    result = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, json.dumps({
        "type": "example", "title": "Data", "payload": {"name": "Oats"}, "metadata": metadata,
    })))
    assert result.artifact is not None
    call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("present", tool.name, "{}"))
    store.record_result(session_id, call, result)
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts[0].payload.metadata == metadata
    assert completed.artifacts[0].payload.payload == {"name": "Oats"}


def test_unadvertised_metadata_is_rejected() -> None:
    tool, store, session_id, reservation = tool_for_session()
    result = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, json.dumps({
        "type": "example", "title": "Data", "payload": {"name": "Oats"}, "metadata": {},
    })))
    assert json.loads(output_text(result))["reason"] == "invalid_metadata"
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts == ()


def test_local_schema_references_and_session_artifact_limit() -> None:
    tool, store, session_id, reservation = tool_for_session()
    async def exercise() -> None:
        registry = ToolRegistry((tool,))
        arguments = json.dumps({"type": "example", "title": "Foodstuff", "payload": {"name": "Oats"}})
        first = await registry.invoke(tool.name, arguments)
        assert first.artifact is not None
        call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("first", tool.name, arguments))
        store.record_result(session_id, call, first)
        second = await registry.invoke(tool.name, arguments)
        call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("second", tool.name, arguments))
        second = store.record_result(session_id, call, second)
        assert json.loads(output_text(second))["kind"] == "limit_reached"
        assert second.artifact is None
    asyncio.run(exercise())
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert len(completed.artifacts) == 1
    assert completed.artifacts[0].payload == PresentationPayload(title="Foodstuff", payload={"name": "Oats"})


@pytest.mark.parametrize("subtitle", ["Example brand", None])
def test_optional_subtitle_is_retained(subtitle: str | None) -> None:
    tool, store, session_id, reservation = tool_for_session()
    arguments = json.dumps({"type": "example", "title": "Oats", "subtitle": subtitle, "payload": {"name": "Oats"}})
    candidate = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, arguments))
    call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("present", tool.name, arguments))
    store.record_result(session_id, call, candidate)
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts[0].payload.subtitle == subtitle


@pytest.mark.parametrize("subtitle", ["", "   ", "x" * 201, 42])
def test_invalid_subtitle_does_not_create_candidate(subtitle: str | int) -> None:
    tool, store, session_id, reservation = tool_for_session()
    arguments = json.dumps({"type": "example", "title": "Oats", "subtitle": subtitle, "payload": {"name": "Oats"}})
    result = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, arguments))
    assert json.loads(output_text(result))["reason"] == "invalid_arguments"
    assert store.complete_turn(session_id, reservation, "completed", "Finished").artifacts == ()


def test_presentation_and_other_tool_sources_are_combined() -> None:
    async def exercise() -> None:
        def execute(call: ToolInvocation) -> ToolExecution[Never]:
            return ToolExecution('{"name":"Oats"}')
        requests: list[AgenticGenerationRequest] = []
        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) == 1:
                    call = AgenticToolCall("read-call", "read_data", "{}")
                elif len(requests) == 2:
                    call = AgenticToolCall("show-call", "present_artifact", json.dumps({
                        "type": "example", "title": "Foodstuff", "payload": {"name": "Oats"},
                    }))
                else:
                    return AgenticGenerationResponse((), (), "Shown")
                return AgenticGenerationResponse(({"type": "function_call", "call_id": call.call_id,
                    "name": call.name, "arguments": call.arguments},), (call,), None)
        agent = create_model_agent(Generator(), tool_sources=(LocalToolSource((RegisteredTool(
            "read_data", {"type": "function", "name": "read_data"}, execute,
        ),), "Read data with read_data"),))
        created = agent.create({"context": {}, "artifactCapabilities": [CAPABILITY]})
        assert isinstance(created, TextSessionCreation)
        agent.append_user_message(created.session_id, "Show")
        result = await agent.execute_turn(created.session_id)
        assert result.kind == "completed"
        assert len(result.artifacts) == 1
        assert {tool["name"] for tool in requests[0].tools} == {"read_data", "present_artifact"}
        assert "Read data with read_data" in requests[0].instructions
        assert "An arbitrary consumer presentation" in requests[0].instructions
        assert CAPABILITY["titleDescription"] in requests[0].instructions
        assert CAPABILITY["subtitleDescription"] in requests[0].instructions
    asyncio.run(exercise())


def test_default_budgets_complete_an_extended_presentation_turn() -> None:
    async def exercise() -> None:
        class Generator:
            def __init__(self) -> None:
                self.responses = 0

            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                self.responses += 1
                if self.responses > 25:
                    return AgenticGenerationResponse((), (), "Shown. " + "Details. " * 600)
                call = AgenticToolCall(str(self.responses), "present_artifact", json.dumps({
                    "type": "example", "title": f"Item {self.responses}",
                    "payload": {"name": f"Item {self.responses}"},
                }))
                return AgenticGenerationResponse(({
                    "type": "function_call", "call_id": call.call_id,
                    "name": call.name, "arguments": call.arguments,
                },), (call,), None)

        generator = Generator()
        agent = create_model_agent(generator)
        created = agent.create({"context": {"description": "x" * 20_000},
                                "artifactCapabilities": [CAPABILITY]})
        assert isinstance(created, TextSessionCreation)
        agent.append_user_message(created.session_id, "Show the requested items. " + "Context. " * 600)
        result = await agent.execute_turn(created.session_id)
        assert result.kind == "completed"
        assert len(result.artifacts) == 25
        assert generator.responses == 26
        assert result.text is not None and len(result.text) > 4_000
        assert [artifact.payload.payload for artifact in result.artifacts] == [
            {"name": f"Item {index}"} for index in range(1, 26)
        ]

    asyncio.run(exercise())


def output_text[ArtifactT](execution: ToolExecution[ArtifactT]) -> str:
    assert isinstance(execution.output, str)
    return execution.output
