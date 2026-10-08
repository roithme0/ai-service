from datetime import timedelta
from typing import cast

import pytest

from app.agents.generation_history import record_generation_item, record_generation_response
from app.agents.history_projection import generation_tool_call, model_input
from app.agents.models.generation import AgenticGenerationResponse, AgenticToolCall
from app.sessions.models.conversation import ConversationSessionSettings, ConversationTurnReservation
from app.sessions.models.history import (
    CallRecord, MessageRecord, MessageRecordKind, TerminalRecord, TurnActivityRecord,
)
from app.sessions.session_store import ConversationSessionStore, TurnHistoryUnavailable


def reserved() -> tuple[ConversationSessionStore[str, str], str, ConversationTurnReservation[str, str]]:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Run")
    turn = store.reserve_turn(session_id)
    assert isinstance(turn, ConversationTurnReservation)
    return store, session_id, turn


def test_session_created_messages_have_no_replay_payload_and_project_for_generation() -> None:
    store, session_id, turn = reserved()
    result = store.complete_turn(session_id, turn, "completed", "Done")
    assert result.kind == "completed" and result.text == "Done"
    history = store.history(session_id)
    messages = [record for record in history if isinstance(record, MessageRecord)]
    assert [(record.kind, record.text, record.item) for record in messages] == [
        ("user", "Run", None), ("final", "Done", None),
    ]
    assert model_input(history) == (
        {"role": "user", "content": "Run"},
        {"type": "message", "role": "assistant", "content": "Done", "phase": "final_answer"},
    )


@pytest.mark.parametrize("kind,phase", [("intermediate", "commentary"), ("unspecified", None)])
def test_native_assistant_messages_project_their_kind(
    kind: MessageRecordKind, phase: str | None,
) -> None:
    projected = model_input((MessageRecord("turn", None, "Working", kind),))[0]
    assert projected["role"] == "assistant" and projected["content"] == "Working"
    if phase is None:
        assert "phase" not in projected
    else:
        assert projected["phase"] == phase


@pytest.mark.parametrize("item", [{}, {"opaque": ["provider metadata"]}])
def test_message_replay_payload_is_preserved_even_when_empty(item: dict[str, object]) -> None:
    record = MessageRecord("turn", item, "Native text", "final")
    projected = model_input((record,))[0]
    assert projected == item
    projected["added"] = True
    assert "added" not in item


def test_history_admission_copies_input_and_returned_records() -> None:
    store, session_id, turn = reserved()
    item: dict[str, object] = {"role": "assistant", "content": "Working"}
    record = MessageRecord(turn.turn_id, item, "Working", "intermediate")
    accepted = store.record_turn_history(session_id, turn.turn_id, (record,))[0]
    assert isinstance(accepted, MessageRecord)
    assert accepted.item is not None
    item["content"] = "Changed input"
    accepted.item["content"] = "Changed return"
    retained = store.history(session_id)[-1]
    assert isinstance(retained, MessageRecord)
    assert retained.item is not None
    assert retained.item["content"] == "Working"


@pytest.mark.parametrize("text", [" ", "x" * 16001])
def test_history_admission_validates_retained_message_text(text: str) -> None:
    store, session_id, turn = reserved()
    record = MessageRecord(turn.turn_id, {"opaque": "payload"}, text, "intermediate")
    before = store.history(session_id)
    with pytest.raises(ValueError, match="assistant message"):
        store.record_turn_history(session_id, turn.turn_id, (record,))
    assert store.history(session_id) == before


@pytest.mark.parametrize("invalid", ["wrong_turn", "user_message", "terminal"])
def test_history_admission_rejects_records_that_bypass_session_lifecycle(invalid: str) -> None:
    store, session_id, turn = reserved()
    record: TurnActivityRecord
    if invalid == "terminal":
        record = cast(TurnActivityRecord, TerminalRecord(turn.turn_id, "completed"))
    else:
        record = MessageRecord(
            "other" if invalid == "wrong_turn" else turn.turn_id,
            {"content": "Text"}, "Text", "user" if invalid == "user_message" else "intermediate",
        )
    before = store.history(session_id)
    with pytest.raises(ValueError):
        store.record_turn_history(session_id, turn.turn_id, (record,))
    assert store.history(session_id) == before


def test_completed_turn_rejects_late_generation_output() -> None:
    store, session_id, turn = reserved()
    store.complete_turn(session_id, turn, "completed", "Done")
    before = store.history(session_id)
    with pytest.raises(TurnHistoryUnavailable):
        record_generation_item(store, session_id, turn.turn_id, {
            "type": "message", "role": "assistant", "content": "Late",
        })
    assert store.history(session_id) == before


def test_response_call_mismatch_rejects_all_output_before_retention() -> None:
    store, session_id, turn = reserved()
    response = AgenticGenerationResponse((
        {"type": "message", "content": "Working", "phase": "commentary"},
        {"type": "function_call", "call_id": "one", "name": "tool", "arguments": "{}"},
    ), (AgenticToolCall("other", "tool", "{}"),), None)
    before = store.history(session_id)
    with pytest.raises(ValueError, match="match in order"):
        record_generation_response(store, session_id, turn.turn_id, response)
    assert store.history(session_id) == before


@pytest.mark.parametrize("field", ["call_id", "name", "arguments"])
def test_response_rejects_nonstring_call_fields_before_retaining_any_output(field: str) -> None:
    store, session_id, turn = reserved()
    item: dict[str, object] = {
        "type": "function_call", "call_id": "call", "name": "tool", "arguments": "{}",
    }
    item[field] = 42
    call_fields = {"call_id": "call", "name": "tool", "arguments": "{}", field: "42"}
    response = AgenticGenerationResponse((
        {"type": "message", "content": "Working", "phase": "commentary"}, item,
    ), (AgenticToolCall(call_fields["call_id"], call_fields["name"], call_fields["arguments"]),), None)
    before = store.history(session_id)
    with pytest.raises(ValueError, match="invalid recorded tool call"):
        record_generation_response(store, session_id, turn.turn_id, response)
    assert store.history(session_id) == before


def test_invalid_later_output_preserves_previously_admitted_activity() -> None:
    store, session_id, turn = reserved()
    response = AgenticGenerationResponse((
        {"type": "message", "content": "Working", "phase": "commentary"},
        {"type": "message", "content": " ", "phase": "final_answer"},
    ), (), None)
    with pytest.raises(ValueError, match="assistant message"):
        record_generation_response(store, session_id, turn.turn_id, response)
    retained = store.history(session_id)
    assert len(retained) == 2
    assert isinstance(retained[-1], MessageRecord)
    assert retained[-1].kind == "intermediate"
    assert retained[-1].item is not None
    assert retained[-1].item["content"] == "Working"


def test_tool_call_replay_preserves_extra_payload_and_uses_retained_metadata() -> None:
    store, session_id, turn = reserved()
    item: dict[str, object] = {
        "type": "function_call", "id": "provider-item", "status": "completed",
        "call_id": "call", "name": "sample", "arguments": '{"value":1}',
    }
    record = record_generation_item(store, session_id, turn.turn_id, item)
    assert isinstance(record, CallRecord)
    assert generation_tool_call(record) == AgenticToolCall("call", "sample", '{"value":1}')
    assert model_input(store.history(session_id))[-1] == item

    record.item["name"] = "changed payload"
    projected = model_input((record,))[0]
    assert projected["name"] == "sample"
    assert projected["id"] == "provider-item"
    assert projected["status"] == "completed"
    projected["arguments"] = "changed projection"
    assert model_input(store.history(session_id))[-1] == item


@pytest.mark.parametrize("field", ["call_id", "name", "arguments"])
def test_invalid_tool_call_metadata_is_rejected_before_retention(field: str) -> None:
    store, session_id, turn = reserved()
    item: dict[str, object] = {
        "type": "function_call", "call_id": "call", "name": "sample", "arguments": "{}",
    }
    item[field] = 42
    before = store.history(session_id)
    with pytest.raises(ValueError, match="invalid recorded tool call"):
        record_generation_item(store, session_id, turn.turn_id, item)
    assert store.history(session_id) == before
