"""Safe ordered UI projection of retained conversation activity."""

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
from app.sessions.models.timeline import (
    TimelineArtifact,
    TimelineFailure,
    TimelineIntermediateMessage,
    TimelineItem,
    TimelineMessage,
    TimelineTool,
    TimelineToolStatus,
)


def timeline(history: tuple[HistoryRecord, ...]) -> tuple[TimelineItem, ...]:
    started = {record.execution_id for record in history if isinstance(record, ExecutionStartedRecord)}
    results = {record.execution_id: record for record in history
               if isinstance(record, (ToolResultRecord, ExecutionReportRecord))}
    user_index = 0
    items: list[TimelineItem] = []
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
            items.append(TimelineArtifact(record.turn_id, record.artifact_id))
        elif isinstance(record, TerminalRecord) and record.kind != "completed":
            items.append(TimelineFailure(record.turn_id))
    return tuple(items)


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
