"""Ordered internal history records and model-facing projections."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, cast

from app.models.agentic_generation import AgenticInputItem, AgenticOutputItem, AgenticToolCall
from app.sessions.text_sessions import TextMessage


@dataclass(frozen=True)
class MessageRecord:
    turn_id: str
    item: AgenticInputItem
    kind: Literal["user", "intermediate", "final", "rejected"]


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
    kind: Literal["completed", "generation_failed", "conflict"]


type HistoryRecord = (
    MessageRecord | ContinuationRecord | CallRecord | ExecutionStartedRecord | ToolResultRecord
    | ExecutionReportRecord | ArtifactRecord | TerminalRecord
)


def model_input(history: tuple[HistoryRecord, ...]) -> tuple[AgenticInputItem, ...]:
    items: list[AgenticInputItem] = []
    for record in history:
        if isinstance(record, MessageRecord) and record.kind != "rejected":
            items.append(deepcopy(record.item))
        elif isinstance(record, (ContinuationRecord, CallRecord)):
            items.append(deepcopy(record.item))
        elif isinstance(record, (ToolResultRecord, ExecutionReportRecord)):
            items.append({"type": "function_call_output", "call_id": record.call_id,
                          "output": record.output if isinstance(record, ToolResultRecord) else record.output()})
    return tuple(items)


def text_messages(history: tuple[HistoryRecord, ...]) -> tuple[TextMessage, ...]:
    completed = {record.turn_id for record in history
                 if isinstance(record, TerminalRecord) and record.kind == "completed"}
    messages: list[TextMessage] = []
    for record in history:
        if not isinstance(record, MessageRecord):
            continue
        if record.kind == "user":
            messages.append(TextMessage("user", message_text(record.item)))
        elif record.kind == "final" and record.turn_id in completed:
            text = message_text(record.item)
            if messages and messages[-1].role == "assistant" and messages[-1].turn_id == record.turn_id:
                previous = messages[-1]
                messages[-1] = TextMessage("assistant", previous.text + text, record.turn_id)
            else:
                messages.append(TextMessage("assistant", text, record.turn_id))
    return tuple(messages)


def message_text(item: AgenticInputItem) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in cast(list[object], content):
            if isinstance(part, dict):
                text = cast(dict[str, object], part).get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "".join(texts)
    return ""
