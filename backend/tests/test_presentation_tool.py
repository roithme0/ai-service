import asyncio
import json
from typing import Never

import pytest

from app.sessions.agent_service import AgentInputAccepted
from app.sessions.context import SessionContext, validate_context_input
from app.sessions.conversation import ConversationSessionSettings, ConversationTurnReservation, StagedArtifact
from app.sessions.model_sessions import ModelSessionStore, create_model_agent, new_model_session_store
from app.sessions.presentation import PresentationPayload, presentation_tool_source
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation, ToolRegistry
from app.sessions.text_sessions import TextSessionCreation
from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall


CAPABILITY = {"type": "example", "description": "An arbitrary consumer presentation",
              "payloadSchema": {"$defs": {"name": {"type": "string"}}, "type": "object",
                                "properties": {"name": {"$ref": "#/$defs/name"}},
                                "required": ["name"], "additionalProperties": False}}


def tool_for_session() -> tuple[
    RegisteredTool[StagedArtifact[PresentationPayload]], ModelSessionStore, str,
    ConversationTurnReservation[SessionContext, PresentationPayload],
]:
    accepted = validate_context_input({"context": {}, "artifactCapabilities": [CAPABILITY]})
    assert isinstance(accepted, AgentInputAccepted)
    store = new_model_session_store()
    session = store.create(accepted.context, ConversationSessionSettings(max_artifacts=1))
    store.append_user_message(session.session_id, "Present")
    reservation = store.reserve_turn(session.session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    source = presentation_tool_source(accepted.context.artifact_capabilities, store, session.session_id, reservation.turn_id)
    return source.registered_tools()[0], store, session.session_id, reservation


@pytest.mark.parametrize("arguments", ["null", "{", '{"type":"example","title":" ","payload":{"name":"Oats"}}',
    '{"type":"example","title":"Data","payload":{"name":NaN}}',
    '{"type":"example","title":"Data","payload":{"name":"Oats"},"extra":true}'])
def test_invalid_arguments_do_not_stage_an_artifact(arguments: str) -> None:
    tool, store, session_id, reservation = tool_for_session()
    async def exercise() -> None:
        result = await ToolRegistry((tool,)).invoke(tool.name, arguments)
        assert json.loads(result.output)["kind"] == "rejected"
        assert result.artifact is None
    asyncio.run(exercise())
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts == ()


def test_local_schema_references_and_session_artifact_limit() -> None:
    tool, store, session_id, reservation = tool_for_session()
    async def exercise() -> None:
        registry = ToolRegistry((tool,))
        arguments = json.dumps({"type": "example", "title": "Foodstuff", "payload": {"name": "Oats"}})
        first = await registry.invoke(tool.name, arguments)
        assert first.artifact is not None
        second = await registry.invoke(tool.name, arguments)
        assert json.loads(second.output)["kind"] == "limit_reached"
        assert second.artifact is None
    asyncio.run(exercise())
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert len(completed.artifacts) == 1
    assert completed.artifacts[0].payload == PresentationPayload(title="Foodstuff", payload={"name": "Oats"})


@pytest.mark.parametrize("subtitle", ["Example brand", None])
def test_optional_subtitle_is_retained(subtitle: str | None) -> None:
    tool, store, session_id, reservation = tool_for_session()
    arguments = json.dumps({"type": "example", "title": "Oats", "subtitle": subtitle, "payload": {"name": "Oats"}})
    asyncio.run(ToolRegistry((tool,)).invoke(tool.name, arguments))
    completed = store.complete_turn(session_id, reservation, "completed", "Finished")
    assert completed.artifacts[0].payload.subtitle == subtitle


@pytest.mark.parametrize("subtitle", ["", "   ", "x" * 201, 42])
def test_invalid_subtitle_does_not_stage_an_artifact(subtitle: str | int) -> None:
    tool, store, session_id, reservation = tool_for_session()
    arguments = json.dumps({"type": "example", "title": "Oats", "subtitle": subtitle, "payload": {"name": "Oats"}})
    result = asyncio.run(ToolRegistry((tool,)).invoke(tool.name, arguments))
    assert json.loads(result.output)["reason"] == "invalid_arguments"
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
    asyncio.run(exercise())
