"""Project retained session history into model input."""

from __future__ import annotations

import json
from copy import deepcopy

from app.agents.models.generation import AgenticInputItem, AgenticToolCall
from app.sessions.models.history import (
    CallRecord,
    ContinuationRecord,
    ExecutionReportRecord,
    HistoryRecord,
    HostedToolRecord,
    MessageRecord,
    ToolResultRecord,
)


def generation_tool_call(record: CallRecord) -> AgenticToolCall:
    return AgenticToolCall(record.call_id, record.name, record.arguments)


def _execution_report_output(record: ExecutionReportRecord) -> str:
    detail = (
        "Execution never started."
        if record.state == "not_executed" else
        "Execution started, but no result was confirmed. The operation may have completed. "
        "Investigate before repeating a state-changing action."
    )
    return json.dumps({"provenance": record.provenance, "kind": "execution_report",
                       "state": record.state, "detail": detail})


def model_input(history: tuple[HistoryRecord, ...]) -> tuple[AgenticInputItem, ...]:
    items: list[AgenticInputItem] = []
    for record in history:
        if isinstance(record, MessageRecord):
            items.append(deepcopy(record.item))
        elif isinstance(record, CallRecord):
            item = deepcopy(record.item)
            item.update(call_id=record.call_id, name=record.name, arguments=record.arguments)
            items.append(item)
        elif isinstance(record, (ContinuationRecord, HostedToolRecord)):
            items.append(deepcopy(record.item))
        elif isinstance(record, (ToolResultRecord, ExecutionReportRecord)):
            items.append({"type": "function_call_output", "call_id": record.call_id,
                          "output": record.output if isinstance(record, ToolResultRecord) else _execution_report_output(record)})
    return tuple(items)

