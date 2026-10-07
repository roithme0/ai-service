"""Safe ordered UI projection of retained conversation activity."""

from app.agents.output_items import message_text
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
            if record.kind == "intermediate":
                items.append(TimelineIntermediateMessage(record.turn_id, f"message-{record.message_id}",
                                                         message_text(record.item), "intermediate"))
            else:
                identity = f"confirmed-{user_index}-user" if record.kind == "user" else f"message-{record.message_id}"
                role: SessionRole = "user" if record.kind == "user" else "assistant"
                items.append(TimelineMessage(record.turn_id, identity, role, message_text(record.item), "message"))
                if record.kind == "user":
                    user_index += 1
        elif isinstance(record, CallRecord):
            result = results.get(record.execution_id)
            status: TimelineToolStatus
            if isinstance(result, ToolResultRecord):
                status = "failed" if result.failed else "completed"
            elif isinstance(result, ExecutionReportRecord):
                status = result.state
            else:
                status = "running" if record.execution_id in started else "requested"
            items.append(TimelineTool(record.turn_id, record.execution_id, record.call.name, status, "tool"))
        elif isinstance(record, HostedToolRecord):
            items.append(TimelineTool(record.turn_id, record.execution_id, "web_search", record.status, "tool"))
        elif isinstance(record, ArtifactRecord):
            items.append(TimelineArtifact(record.turn_id, record.artifact_id, "artifact"))
        elif isinstance(record, TerminalRecord) and record.kind != "completed":
            items.append(TimelineFailure(record.turn_id, "failure"))
    return tuple(items)
