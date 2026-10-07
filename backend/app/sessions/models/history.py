"""Ordered records of conversation messages, execution, and artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from app.agents.models.generation import AgenticInputItem, AgenticOutputItem, AgenticToolCall
from app.sessions.models.turns import TerminalTurnKind


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

