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


def _generation_message(record: MessageRecord) -> AgenticInputItem:
    if record.item is not None:
        return deepcopy(record.item)
    if record.kind == "user":
        return {"role": "user", "content": record.text}
    item: AgenticInputItem = {"type": "message", "role": "assistant", "content": record.text}
    if record.kind == "final":
        item["phase"] = "final_answer"
    elif record.kind == "intermediate":
        item["phase"] = "commentary"
    return item


def _execution_report_output(record: ExecutionReportRecord) -> str:
    detail = (
        "Execution never started."
        if record.state == "not_executed" else
        "Execution started, but no result was confirmed. The operation may have completed. "
        "Investigate before repeating a state-changing action."
    )
    return json.dumps({"provenance": record.provenance, "kind": "execution_report",
                       "state": record.state, "detail": detail})


def _generation_call(record: CallRecord) -> AgenticInputItem:
    item = deepcopy(record.item)
    item.update(call_id=record.call_id, name=record.name, arguments=record.arguments)
    return item


def _generation_tool_output(record: ToolResultRecord | ExecutionReportRecord) -> AgenticInputItem:
    output = record.output if isinstance(record, ToolResultRecord) else _execution_report_output(record)
    return {"type": "function_call_output", "call_id": record.call_id, "output": output}


def model_input(history: tuple[HistoryRecord, ...]) -> tuple[AgenticInputItem, ...]:
    items: list[AgenticInputItem] = []
    for record in history:
        if isinstance(record, MessageRecord):
            items.append(_generation_message(record))
        elif isinstance(record, CallRecord):
            items.append(_generation_call(record))
        elif isinstance(record, (ContinuationRecord, HostedToolRecord)):
            items.append(deepcopy(record.item))
        elif isinstance(record, (ToolResultRecord, ExecutionReportRecord)):
            items.append(_generation_tool_output(record))
    return tuple(items)

