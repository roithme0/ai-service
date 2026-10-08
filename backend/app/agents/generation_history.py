"""Adapt generation output into session-owned turn history."""

from collections.abc import Iterator
from copy import deepcopy
from typing import TypeVar
from uuid import uuid4

from app.agents.generation_messages import message_phase, message_text, validate_message_item
from app.agents.models.generation import (
    AgenticGenerationResponse, AgenticOutputItem, AgenticToolCall, AssistantMessagePhase,
)
from app.sessions.models.history import (
    CallRecord,
    ContinuationRecord,
    HostedToolRecord,
    MessageRecord,
    MessageRecordKind,
    TurnActivityRecord,
)
from app.sessions.session_store import ConversationSessionStore

ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")


def tool_call_from_output(item: AgenticOutputItem) -> AgenticToolCall:
    call_id, name, arguments = (item.get(key) for key in ("call_id", "name", "arguments"))
    if not isinstance(call_id, str) or not isinstance(name, str) or not isinstance(arguments, str):
        raise ValueError("invalid recorded tool call")
    return AgenticToolCall(call_id, name, arguments)


def validate_response_tool_calls(response: AgenticGenerationResponse) -> None:
    calls = tuple(
        tool_call_from_output(item)
        for item in response.output_items if item.get("type") == "function_call"
    )
    if calls != response.tool_calls:
        raise ValueError("provider output and requested calls must match in order")


def _message_kind(phase: AssistantMessagePhase | None) -> MessageRecordKind:
    if phase == "commentary":
        return "intermediate"
    if phase == "final_answer":
        return "final"
    return "unspecified"


def _generation_record(turn_id: str, item: AgenticOutputItem) -> TurnActivityRecord:
    validate_message_item(item)
    copied = deepcopy(item)
    if copied.get("phase") is None:
        copied.pop("phase", None)
    if item.get("type") == "function_call":
        call = tool_call_from_output(item)
        return CallRecord(turn_id, str(uuid4()), copied, call.call_id, call.name, call.arguments)
    if item.get("type") == "web_search_call":
        status = item.get("status")
        search_id = item.get("id")
        if (
            status not in ("completed", "failed")
            or not isinstance(search_id, str)
            or not search_id
        ):
            raise ValueError("invalid hosted search activity")
        return HostedToolRecord(turn_id, str(uuid4()), copied, status)
    if item.get("type") == "message":
        return MessageRecord(
            turn_id, copied, message_text(item), _message_kind(message_phase(item)),
        )
    return ContinuationRecord(turn_id, copied)


def record_generation_response(
    store: ConversationSessionStore[ContextT, ArtifactT],
    session_id: str,
    turn_id: str,
    response: AgenticGenerationResponse,
) -> tuple[CallRecord, ...]:
    def records() -> Iterator[TurnActivityRecord]:
        validate_response_tool_calls(response)
        for item in response.output_items:
            yield _generation_record(turn_id, item)

    accepted = store.record_turn_history(session_id, turn_id, records())
    return tuple(record for record in accepted if isinstance(record, CallRecord))


def record_generation_item(
    store: ConversationSessionStore[ContextT, ArtifactT],
    session_id: str,
    turn_id: str,
    item: AgenticOutputItem,
) -> TurnActivityRecord:
    def records() -> Iterator[TurnActivityRecord]:
        yield _generation_record(turn_id, item)

    return store.record_turn_history(session_id, turn_id, records())[0]


def record_tool_call(
    store: ConversationSessionStore[ContextT, ArtifactT],
    session_id: str,
    turn_id: str,
    call: AgenticToolCall,
) -> CallRecord:
    record = record_generation_item(store, session_id, turn_id, {
        "type": "function_call", "call_id": call.call_id,
        "name": call.name, "arguments": call.arguments,
    })
    assert isinstance(record, CallRecord)
    return record
