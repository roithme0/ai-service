"""In-memory recording callbacks for standalone orchestration tests."""

from copy import deepcopy

from app.agents.agentic_generation import AgenticOutputItem, message_phase
from app.sessions.models.history import CallRecord, ContinuationRecord, HistoryRecord, MessageRecord
from app.sessions.models.execution import ToolExecution


class ToolTurnRecorder[ArtifactT]:
    def __init__(self) -> None:
        self.items: list[HistoryRecord] = []
        self.calls: list[CallRecord] = []
        self.started: list[CallRecord] = []
        self.results: list[tuple[CallRecord, ToolExecution[ArtifactT]]] = []

    def record_item(self, item: AgenticOutputItem) -> HistoryRecord:
        record: HistoryRecord
        if item.get("type") == "function_call":
            record = CallRecord("test-turn", str(len(self.calls)), deepcopy(item))
            self.calls.append(record)
        elif item.get("type") == "message":
            phase = message_phase(item)
            record = MessageRecord("test-turn", deepcopy(item), "intermediate" if phase == "commentary" else
                                   "final" if phase == "final_answer" else "unspecified")
        else:
            record = ContinuationRecord("test-turn", deepcopy(item))
        self.items.append(record)
        return record

    def start_execution(self, call: CallRecord) -> None:
        self.started.append(call)

    def record_result(self, call: CallRecord, execution: ToolExecution[ArtifactT]) -> ToolExecution[ArtifactT]:
        self.results.append((call, execution))
        return execution
