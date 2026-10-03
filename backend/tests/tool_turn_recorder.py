"""In-memory recording callbacks for standalone orchestration tests."""

from copy import deepcopy

from app.models.agentic_generation import AgenticGenerationResponse
from app.sessions.history import CallRecord
from app.sessions.tools import ToolExecution


class ToolTurnRecorder[ArtifactT]:
    def __init__(self) -> None:
        self.responses: list[tuple[AgenticGenerationResponse, bool | None]] = []
        self.calls: list[CallRecord] = []
        self.started: list[CallRecord] = []
        self.results: list[tuple[CallRecord, ToolExecution[ArtifactT]]] = []

    def record_response(self, response: AgenticGenerationResponse, accepted: bool | None) -> tuple[CallRecord, ...]:
        self.responses.append((response, accepted))
        calls: list[CallRecord] = []
        for item in response.output_items:
            if item.get("type") == "function_call":
                record = CallRecord("test-turn", str(len(self.calls)), deepcopy(item))
                self.calls.append(record)
                calls.append(record)
        return tuple(calls)

    def start_execution(self, call: CallRecord) -> None:
        self.started.append(call)

    def record_result(self, call: CallRecord, execution: ToolExecution[ArtifactT]) -> ToolExecution[ArtifactT]:
        self.results.append((call, execution))
        return execution
