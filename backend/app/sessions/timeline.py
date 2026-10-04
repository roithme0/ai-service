"""Safe ordered UI projection of retained conversation activity."""

from dataclasses import dataclass
from typing import Literal

from app.models.output_items import message_text
from app.sessions.history import (
    ArtifactRecord, CallRecord, ExecutionReportRecord, HistoryRecord, MessageRecord,
    TerminalRecord, ToolResultRecord, text_messages,
)


@dataclass(frozen=True)
class TimelineMessage:
    turn_id: str
    id: str
    role: Literal["user", "assistant"]
    text: str
    kind: Literal["message"]


@dataclass(frozen=True)
class TimelineIntermediateMessage:
    turn_id: str
    id: str
    text: str
    kind: Literal["intermediate"]


@dataclass(frozen=True)
class TimelineTool:
    turn_id: str
    execution_id: str
    name: str
    status: Literal["completed", "failed", "not_executed", "outcome_unknown"]
    kind: Literal["tool"]


@dataclass(frozen=True)
class TimelineArtifact:
    turn_id: str
    artifact_id: str
    kind: Literal["artifact"]


@dataclass(frozen=True)
class TimelineFailure:
    turn_id: str
    kind: Literal["failure"]


type TimelineItem = TimelineMessage | TimelineIntermediateMessage | TimelineTool | TimelineArtifact | TimelineFailure


def timeline(history: tuple[HistoryRecord, ...], active_turn_id: str | None = None) -> tuple[TimelineItem, ...]:
    messages = iter(enumerate(text_messages(history)))
    results = {record.execution_id: record for record in history
               if isinstance(record, (ToolResultRecord, ExecutionReportRecord))}
    completed = {record.turn_id for record in history
                 if isinstance(record, TerminalRecord) and record.kind == "completed"}
    emitted_answers: set[str] = set()
    items: list[TimelineItem] = []
    for history_index, record in enumerate(history):
        if record.turn_id == active_turn_id and not (isinstance(record, MessageRecord) and record.kind == "user"):
            continue
        if isinstance(record, MessageRecord):
            if record.kind == "intermediate":
                items.append(TimelineIntermediateMessage(record.turn_id, f"intermediate-{record.turn_id}-{history_index}",
                                                  message_text(record.item), "intermediate"))
            elif record.kind == "user" or (record.kind == "final" and record.turn_id in completed
                                        and record.turn_id not in emitted_answers):
                index, message = next(messages)
                identity = f"confirmed-{index}-user" if message.role == "user" else f"assistant-{record.turn_id}"
                items.append(TimelineMessage(record.turn_id, identity, message.role, message.text, "message"))
                if record.kind == "final":
                    emitted_answers.add(record.turn_id)
            elif record.kind == "unspecified":
                items.append(TimelineMessage(record.turn_id, f"message-{record.message_id}", "assistant",
                                             message_text(record.item), "message"))
        elif isinstance(record, CallRecord):
            result = results.get(record.execution_id)
            status: Literal["completed", "failed", "not_executed", "outcome_unknown"]
            if isinstance(result, ToolResultRecord):
                status = "failed" if result.failed else "completed"
            elif isinstance(result, ExecutionReportRecord):
                status = result.state
            else:
                continue
            items.append(TimelineTool(record.turn_id, record.execution_id, record.call.name, status, "tool"))
        elif isinstance(record, ArtifactRecord):
            items.append(TimelineArtifact(record.turn_id, record.artifact_id, "artifact"))
        elif isinstance(record, TerminalRecord) and record.kind != "completed":
            items.append(TimelineFailure(record.turn_id, "failure"))
    return tuple(items)
