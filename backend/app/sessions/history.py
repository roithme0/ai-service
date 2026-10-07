"""Ordered internal history records and model-facing projections."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from app.agents.agentic_generation import AgenticInputItem, AgenticOutputItem, AgenticToolCall
from app.agents.output_items import message_text
from app.sessions.text_sessions import TextMessage
from app.sessions.turn_types import TerminalTurnKind


@dataclass(frozen=True)
class MessageRecord:
    turn_id: str
    item: AgenticInputItem
    kind: Literal["user", "intermediate", "final", "unspecified"]
    message_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ContinuationRecord:
    turn_id: str
    item: AgenticOutputItem


@dataclass(frozen=True)
class CallRecord:
    turn_id: str
    execution_id: str
    item: AgenticOutputItem

    @property
    def call(self) -> AgenticToolCall:
        call_id, name, arguments = (self.item.get(key) for key in ("call_id", "name", "arguments"))
        if not isinstance(call_id, str) or not isinstance(name, str) or not isinstance(arguments, str):
            raise ValueError("invalid recorded tool call")
        return AgenticToolCall(call_id, name, arguments)


@dataclass(frozen=True)
class ExecutionStartedRecord:
    turn_id: str
    execution_id: str


@dataclass(frozen=True)
class HostedToolRecord:
    turn_id: str
    execution_id: str
    item: AgenticOutputItem
    status: Literal["completed", "failed"]


@dataclass(frozen=True)
class ToolResultRecord:
    turn_id: str
    execution_id: str
    call_id: str
    output: str
    failed: bool = False


@dataclass(frozen=True)
class ExecutionReportRecord:
    turn_id: str
    execution_id: str
    call_id: str
    state: Literal["not_executed", "outcome_unknown"]
    provenance: Literal["service"] = "service"

    def output(self) -> str:
        detail = (
            "Execution never started."
            if self.state == "not_executed" else
            "Execution started, but no result was confirmed. The operation may have completed. "
            "Investigate before repeating a state-changing action."
        )
        return json.dumps({"provenance": self.provenance, "kind": "execution_report",
                           "state": self.state, "detail": detail})


@dataclass(frozen=True)
class ArtifactRecord:
    turn_id: str
    execution_id: str
    artifact_id: str


@dataclass(frozen=True)
class TerminalRecord:
    turn_id: str
    kind: TerminalTurnKind


type HistoryRecord = (
    MessageRecord | ContinuationRecord | CallRecord | ExecutionStartedRecord | ToolResultRecord
    | ExecutionReportRecord | HostedToolRecord | ArtifactRecord | TerminalRecord
)


def model_input(history: tuple[HistoryRecord, ...]) -> tuple[AgenticInputItem, ...]:
    items: list[AgenticInputItem] = []
    for record in history:
        if isinstance(record, MessageRecord):
            items.append(deepcopy(record.item))
        elif isinstance(record, (ContinuationRecord, CallRecord, HostedToolRecord)):
            items.append(deepcopy(record.item))
        elif isinstance(record, (ToolResultRecord, ExecutionReportRecord)):
            items.append({"type": "function_call_output", "call_id": record.call_id,
                          "output": record.output if isinstance(record, ToolResultRecord) else record.output()})
    return tuple(items)


def text_messages(history: tuple[HistoryRecord, ...]) -> tuple[TextMessage, ...]:
    completed = {record.turn_id for record in history
                 if isinstance(record, TerminalRecord) and record.kind == "completed"}
    emitted: set[str] = set()
    messages: list[TextMessage] = []
    for record in history:
        if not isinstance(record, MessageRecord):
            continue
        if record.kind == "user":
            messages.append(TextMessage("user", message_text(record.item)))
        elif record.kind == "final" and record.turn_id in completed and record.turn_id not in emitted:
            messages.append(TextMessage("assistant", message_text(record.item), record.turn_id))
            emitted.add(record.turn_id)
    return tuple(messages)
