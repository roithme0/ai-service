"""Safe ordered UI projection of retained conversation activity."""

from typing import TypeVar

from app.sessions.models.artifacts import PublishedArtifact
from app.sessions.models.history import (
    ArtifactRecord,
    CallRecord,
    ExecutionReportRecord,
    ExecutionStartedRecord,
    HistoryRecord,
    HostedToolRecord,
    MessageRecord,
    TerminalRecord,
    ToolResultRecord,
)
from app.sessions.models.session import SessionRole
from app.sessions.models.turns import TurnSnapshot, TurnSnapshotStatus
from app.sessions.models.timeline import (
    TimelineArtifact,
    TimelineFailure,
    TimelineIntermediateMessage,
    TimelineItem,
    TimelineMessage,
    TimelineTool,
    TimelineToolStatus,
)


ArtifactT = TypeVar("ArtifactT")


def timeline(
    history: tuple[HistoryRecord, ...], artifacts: tuple[PublishedArtifact[ArtifactT], ...],
) -> tuple[TimelineItem[ArtifactT], ...]:
    envelopes = {artifact.artifact_id: artifact for artifact in artifacts}
    started = {record.execution_id for record in history if isinstance(record, ExecutionStartedRecord)}
    results = {record.execution_id: record for record in history
               if isinstance(record, (ToolResultRecord, ExecutionReportRecord))}
    user_index = 0
    items: list[TimelineItem[ArtifactT]] = []
    for record in history:
        if isinstance(record, MessageRecord):
            items.append(_message_item(record, user_index))
            if record.kind == "user":
                user_index += 1
        elif isinstance(record, CallRecord):
            items.append(_tool_item(
                record, results.get(record.execution_id), record.execution_id in started
            ))
        elif isinstance(record, HostedToolRecord):
            items.append(TimelineTool(record.turn_id, record.execution_id, "web_search", record.status))
        elif isinstance(record, ArtifactRecord):
            items.append(TimelineArtifact(record.turn_id, envelopes[record.artifact_id]))
        elif isinstance(record, TerminalRecord) and record.kind != "completed":
            items.append(TimelineFailure(record.turn_id))
    return tuple(items)


def turn_snapshots(
    history: tuple[HistoryRecord, ...], items: tuple[TimelineItem[ArtifactT], ...], active_turn_id: str | None,
) -> tuple[TurnSnapshot[ArtifactT], ...]:
    outcomes = {record.turn_id: record.kind for record in history
                if isinstance(record, TerminalRecord)}
    final_turn_ids = {record.turn_id for record in history
                      if isinstance(record, MessageRecord) and record.kind == "final"}
    turns: list[TurnSnapshot[ArtifactT]] = []
    for item in items:
        if not isinstance(item, TimelineMessage) or item.role != "user":
            continue
        status: TurnSnapshotStatus
        if item.turn_id in outcomes:
            status = outcomes[item.turn_id]
        elif item.turn_id == active_turn_id:
            status = "closing" if item.turn_id in final_turn_ids else "in_progress"
        else:
            status = "pending"
        turns.append(TurnSnapshot(item.turn_id, item.id, status, tuple(
            fragment for fragment in items if fragment.turn_id == item.turn_id
        )))
    return tuple(turns)


def _message_item(
    record: MessageRecord, user_index: int,
) -> TimelineMessage | TimelineIntermediateMessage:
    if record.kind == "intermediate":
        return TimelineIntermediateMessage(
            record.turn_id, f"message-{record.message_id}", record.text
        )
    identity = (
        f"confirmed-{user_index}-user"
        if record.kind == "user"
        else f"message-{record.message_id}"
    )
    role: SessionRole = "user" if record.kind == "user" else "assistant"
    return TimelineMessage(record.turn_id, identity, role, record.text)


def _tool_item(
    record: CallRecord,
    result: ToolResultRecord | ExecutionReportRecord | None,
    started: bool,
) -> TimelineTool:
    status: TimelineToolStatus
    if isinstance(result, ToolResultRecord):
        status = "failed" if result.failed else "completed"
    elif isinstance(result, ExecutionReportRecord):
        status = result.state
    else:
        status = "running" if started else "requested"
    return TimelineTool(record.turn_id, record.execution_id, record.name, status)
