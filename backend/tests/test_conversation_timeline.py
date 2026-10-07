import json
from datetime import timedelta

from app.agents.models.generation import AgenticGenerationResponse, AgenticToolCall
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.models.conversation import ConversationReadActive, ConversationSessionSettings, ConversationTurnReservation
from app.sessions.conversation import ConversationSessionStore
from app.agents.history_projection import model_input
from app.sessions.models.timeline import TimelineArtifact, TimelineFailure, TimelineMessage, TimelineTool
from app.sessions.models.execution import ToolExecution


def test_timeline_preserves_placement_failure_survival_and_safe_statuses() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("private context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Show results")
    turn = store.reserve_turn(session_id)
    assert isinstance(turn, ConversationTurnReservation)
    store.record_provider_response(session_id, turn.turn_id, AgenticGenerationResponse((
        {"type": "message", "role": "assistant", "phase": "commentary", "content": "Checking results."},
    ), (), "Checking results."))
    first = store.record_call(session_id, turn.turn_id, AgenticToolCall("same", "present", '{"secret":"argument"}'))
    store.start_execution(session_id, first)
    accepted = store.record_result(session_id, first, ToolExecution(
        ArtifactToolOutput("presented"), ArtifactCandidate("example", "retained content")))
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert [item.kind for item in read.snapshot.timeline] == ["message", "intermediate", "tool", "artifact"]
    assert len(read.snapshot.artifacts) == 1

    calls = tuple(AgenticToolCall(str(index), name, "{}") for index, name in enumerate(
        ("explicit_failure", "domain_payload", "uncertain", "never_started")))
    response = AgenticGenerationResponse((
        {"type": "reasoning", "encrypted_content": "secret reasoning"},
        *({"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments} for call in calls),
    ), calls, None)
    failed, ordinary, uncertain, never_started = store.record_provider_response(session_id, turn.turn_id, response)
    store.start_execution(session_id, failed)
    store.record_result(session_id, failed, ToolExecution("explicit error detail", failed=True))
    store.start_execution(session_id, ordinary)
    store.record_result(session_id, ordinary, ToolExecution('{"kind":"failed","secret":"domain data"}'))
    store.start_execution(session_id, uncertain)
    store.fail_turn(session_id, turn)

    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    items = read.snapshot.timeline
    assert [item.kind for item in items] == ["message", "intermediate", "tool", "artifact", "tool", "tool", "tool", "tool", "failure"]
    tools = [item for item in items if isinstance(item, TimelineTool)]
    assert [item.status for item in tools] == ["completed", "failed", "completed", "outcome_unknown", "not_executed"]
    assert tools[-1].execution_id == never_started.execution_id
    artifact = items[3]
    assert isinstance(artifact, TimelineArtifact)
    assert artifact.artifact_id == read.snapshot.artifacts[0].artifact_id
    assert isinstance(accepted.output, str)
    assert json.loads(accepted.output)["artifact_id"] == artifact.artifact_id
    assert read.snapshot.artifacts[0].payload == "retained content"
    assert "secret" not in repr(items) and "explicit error detail" not in repr(items)
    assert model_input(store.history(session_id))[3]["output"] == accepted.output

    store.append_user_message(session_id, "Continue")
    next_turn = store.reserve_turn(session_id)
    assert isinstance(next_turn, ConversationTurnReservation)
    store.complete_turn(session_id, next_turn, "completed", "Done")
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.timeline[:len(items)] == items
    assert isinstance(read.snapshot.timeline[-3], TimelineFailure)
    assert isinstance(read.snapshot.timeline[-1], TimelineMessage)
    assert read.snapshot.timeline[-1].text == "Done"
