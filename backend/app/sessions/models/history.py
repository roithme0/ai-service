"""Ordered records of conversation messages, execution, and artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from app.sessions.models.turns import TerminalTurnKind


type HistoryPayload = dict[str, object]


MessageRecordKind = Literal["user", "intermediate", "final", "unspecified"]
HostedToolStatus = Literal["completed", "failed"]
ExecutionReportState = Literal["not_executed", "outcome_unknown"]


@dataclass(frozen=True)
class MessageRecord:
    turn_id: str
    item: HistoryPayload | None
    text: str
    kind: MessageRecordKind
    message_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class ContinuationRecord:
    turn_id: str
    item: HistoryPayload


@dataclass(frozen=True)
class CallRecord:
    turn_id: str
    execution_id: str
    item: HistoryPayload
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ExecutionStartedRecord:
    turn_id: str
    execution_id: str


@dataclass(frozen=True)
class HostedToolRecord:
    turn_id: str
    execution_id: str
    item: HistoryPayload
    status: HostedToolStatus


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
    state: ExecutionReportState
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


type TurnActivityRecord = MessageRecord | ContinuationRecord | CallRecord | HostedToolRecord


type HistoryRecord = (
    MessageRecord | ContinuationRecord | CallRecord | ExecutionStartedRecord | ToolResultRecord
    | ExecutionReportRecord | HostedToolRecord | ArtifactRecord | TerminalRecord
)

