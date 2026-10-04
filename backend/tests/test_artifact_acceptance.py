"""Artifact candidate acceptance regressions replacing obsolete staging registry tests."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.conversation import ConversationReadActive, ConversationSessionSettings, ConversationSessionStore, ConversationTurnReservation, TurnHistoryUnavailable
from app.sessions.history import ArtifactRecord, CallRecord, ExecutionReportRecord, ToolResultRecord, model_input
from app.sessions.model_turns import ModelTurnStrategy
from reserved_turn import execute_reserved_turn
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation


def ready(limit: int = 2) -> tuple[ConversationSessionStore[str, list[str]], str]:
    store = ConversationSessionStore[str, list[str]](timedelta(minutes=90))
    session_id = store.create("context", ConversationSessionSettings(limit)).session_id
    store.append_user_message(session_id, "present")
    return store, session_id


def setup(limit: int = 2) -> tuple[ConversationSessionStore[str, list[str]], str, ConversationTurnReservation[str, list[str]]]:
    store, session_id = ready(limit)
    turn = store.reserve_turn(session_id)
    assert isinstance(turn, ConversationTurnReservation)
    return store, session_id, turn


def start(store: ConversationSessionStore[str, list[str]], session_id: str,
          turn: ConversationTurnReservation[str, list[str]], call_id: str = "same") -> CallRecord:
    call = store.record_call(session_id, turn.turn_id, AgenticToolCall(call_id, "present", "{}"))
    store.start_execution(session_id, call)
    return call


def candidate(value: str = "data") -> ToolExecution[ArtifactCandidate[list[str]]]:
    return ToolExecution(ArtifactToolOutput("presented"), ArtifactCandidate("example", [value]))


def test_acceptance_assigns_identity_atomically_and_failure_retains_capacity() -> None:
    store, session_id, turn = setup(1)
    call = start(store, session_id, turn)
    before = store.history(session_id)
    local = candidate()
    assert store.history(session_id) == before
    assert not hasattr(local.artifact, "artifact_id")
    finalized = store.record_result(session_id, call, local)
    history = store.history(session_id)
    assert isinstance(history[-2], ToolResultRecord)
    assert isinstance(history[-1], ArtifactRecord)
    assert history[-1].execution_id == history[-2].execution_id == call.execution_id
    assert json.loads(output_text(finalized))["artifact_id"] == history[-1].artifact_id
    assert model_input(history)[-1]["output"] == finalized.output
    assert len(store.read(session_id).snapshot.artifacts) == 1
    store.fail_turn(session_id, turn)
    retained = store.read(session_id).snapshot.artifacts
    assert retained[0].order == len(before) + 2
    assert retained[0].created_at.tzinfo == UTC
    store.append_user_message(session_id, "next")
    next_turn = store.reserve_turn(session_id)
    assert isinstance(next_turn, ConversationTurnReservation)
    next_call = start(store, session_id, next_turn)
    assert next_call.execution_id != call.execution_id
    with patch("app.sessions.conversation.uuid4", side_effect=AssertionError("must not allocate")):
        rejected = store.record_result(session_id, next_call, candidate("overflow"))
    assert json.loads(output_text(rejected)) == {"kind": "limit_reached"}
    assert rejected.artifact is None
    store.fail_turn(session_id, next_turn)
    assert store.read(session_id).snapshot.artifacts == retained
    assert not any(isinstance(record, ExecutionReportRecord) for record in store.history(session_id))


def test_duplicate_acceptance_is_rejected_under_lock() -> None:
    store, session_id, turn = setup()
    call = start(store, session_id, turn)
    def accept() -> bool:
        try:
            store.record_result(session_id, call, candidate())
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: accept(), range(2)))
    assert sorted(outcomes) == [False, True]
    history = store.history(session_id)
    assert sum(isinstance(record, ToolResultRecord) for record in history) == 1
    assert sum(isinstance(record, ArtifactRecord) for record in history) == 1


def test_candidate_and_snapshot_payloads_are_detached_and_session_isolated() -> None:
    store, session_id, turn = setup()
    other = store.create("other", ConversationSessionSettings(2)).session_id
    local = candidate()
    finalized = store.record_result(session_id, start(store, session_id, turn), local)
    assert local.artifact is not None and finalized.artifact is not None
    local.artifact.payload.append("mutated input")
    finalized.artifact.payload.append("mutated return")
    record = store.history(session_id)[-1]
    assert isinstance(record, ArtifactRecord)
    assert not hasattr(record, "artifact")
    assert record.artifact_id == json.loads(output_text(finalized))["artifact_id"]
    store.complete_turn(session_id, turn, "completed", "done")
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts[0].payload == ["data"]
    read.snapshot.artifacts[0].payload.append("mutated snapshot")
    assert store.read(session_id).snapshot.artifacts[0].payload == ["data"]
    assert store.history(other) == ()
    assert store.read(other).snapshot.artifacts == ()


def test_history_position_follows_acceptance_order() -> None:
    store, session_id, turn = setup()
    first = start(store, session_id, turn, "first")
    second = start(store, session_id, turn, "second")
    store.record_result(session_id, second, candidate("second"))
    store.record_result(session_id, first, candidate("first"))
    store.fail_turn(session_id, turn)
    records = [(index, record.artifact_id) for index, record in enumerate(store.history(session_id), 1)
               if isinstance(record, ArtifactRecord)]
    read = store.read(session_id)
    assert [(artifact.order, artifact.artifact_id) for artifact in read.snapshot.artifacts] == records
    assert [artifact.payload for artifact in read.snapshot.artifacts] == [["second"], ["first"]]


@pytest.mark.parametrize("cancel", [False, True])
def test_tool_failure_or_cancellation_before_return_never_accepts_candidate(cancel: bool) -> None:
    async def exercise() -> None:
        store, session_id = ready()
        entered = asyncio.Event()
        async def execute(invocation: ToolInvocation) -> ToolExecution[ArtifactCandidate[list[str]]]:
            local = candidate()
            assert local.artifact is not None
            assert not any(isinstance(record, ArtifactRecord) for record in store.history(session_id))
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise RuntimeError("tool did not return")
        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                call = AgenticToolCall("present", "present", "{}")
                return AgenticGenerationResponse(({"type": "function_call", "call_id": call.call_id,
                    "name": call.name, "arguments": call.arguments},), (call,), None)
        strategy = ModelTurnStrategy(store, Generator(), str, (LocalToolSource((RegisteredTool(
            "present", {"type": "function", "name": "present"}, execute),)),))
        task = asyncio.create_task(execute_reserved_turn(store, strategy, session_id))
        await entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).kind == "generation_failed"
        history = store.history(session_id)
        assert not any(isinstance(record, (ToolResultRecord, ArtifactRecord)) for record in history)
        reports = [record for record in history if isinstance(record, ExecutionReportRecord)]
        assert len(reports) == 1 and reports[0].state == "outcome_unknown"
    asyncio.run(exercise())


@pytest.mark.parametrize("later_failure", [False, True])
def test_model_consumes_assigned_id_and_replay_preserves_same_output(later_failure: bool) -> None:
    store, session_id = ready()
    outputs: list[str] = []
    class Generator:
        count = 0
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            self.count += 1
            if self.count == 1:
                call = AgenticToolCall("same", "present", "{}")
                return AgenticGenerationResponse(({"type": "function_call", "call_id": call.call_id,
                    "name": call.name, "arguments": call.arguments},), (call,), None)
            output = next(str(item["output"]) for item in request.input_items if item.get("type") == "function_call_output")
            outputs.append(output)
            record = next(record for record in store.history(session_id) if isinstance(record, ArtifactRecord))
            assert json.loads(output)["artifact_id"] == record.artifact_id
            if self.count == 2 and later_failure:
                raise RuntimeError("later model failed")
            return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "shown"},), (), "shown")
    def execute(invocation: ToolInvocation) -> ToolExecution[ArtifactCandidate[list[str]]]:
        assert not any(isinstance(record, ArtifactRecord) for record in store.history(session_id))
        return candidate()
    strategy = ModelTurnStrategy(store, Generator(), str, (LocalToolSource((RegisteredTool(
        "present", {"type": "function", "name": "present"}, execute),)),))
    result = asyncio.run(execute_reserved_turn(store, strategy, session_id))
    assert result.kind == ("generation_failed" if later_failure else "completed")
    assert len(store.read(session_id).snapshot.artifacts) == 1
    store.append_user_message(session_id, "next")
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == "completed"
    assert len(outputs) == 2 and outputs[0] == outputs[1]


def test_expiry_removes_artifact_map_and_rejects_late_acceptance() -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    store = ConversationSessionStore[str, list[str]](timedelta(minutes=90), lambda: now)
    created = store.create("context", ConversationSessionSettings(2))
    store.append_user_message(created.session_id, "present")
    turn = store.reserve_turn(created.session_id)
    assert isinstance(turn, ConversationTurnReservation)
    first = start(store, created.session_id, turn, "first")
    store.record_result(created.session_id, first, candidate())
    late = start(store, created.session_id, turn, "late")
    now = created.expires_at
    with pytest.raises(TurnHistoryUnavailable) as error:
        store.record_result(created.session_id, late, candidate())
    assert error.value.kind == "expired"
    assert store.history(created.session_id) == ()
    assert created.session_id not in store._history
    assert created.session_id not in store._artifacts
    assert created.session_id not in store._active_turns


def test_invalid_candidate_outcome_does_not_append_partial_result() -> None:
    store, session_id, turn = setup()
    call = start(store, session_id, turn)
    before = store.history(session_id)
    with pytest.raises(ValueError):
        store.record_result(session_id, call, ToolExecution("arbitrary domain output", ArtifactCandidate("example", ["data"])))
    assert store.history(session_id) == before
    assert store._artifacts[session_id] == {}


@pytest.mark.parametrize("copy_number", [1, 2])
def test_copy_failure_is_atomic_and_does_not_allocate_identity(copy_number: int) -> None:
    store, session_id, turn = setup()
    call = start(store, session_id, turn)
    before = store.history(session_id)
    from copy import deepcopy
    copies = 0
    def fail_copy(value: object) -> object:
        nonlocal copies
        if isinstance(value, (list, ArtifactCandidate)):
            copies += 1
            if copies == copy_number:
                raise ValueError("payload copy failed")
        return deepcopy(value)
    with patch("app.sessions.conversation.deepcopy", side_effect=fail_copy), patch(
        "app.sessions.conversation.uuid4", side_effect=AssertionError("must not allocate")):
        with pytest.raises(ValueError, match="payload copy failed"):
            store.record_result(session_id, call, candidate())
    assert store.history(session_id) == before
    assert store._artifacts[session_id] == {}


def test_expiry_between_acceptance_check_and_timestamp_allocates_no_identity() -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    store = ConversationSessionStore[str, list[str]](timedelta(minutes=90), lambda: now)
    created = store.create("context", ConversationSessionSettings(2))
    store.append_user_message(created.session_id, "present")
    turn = store.reserve_turn(created.session_id)
    assert isinstance(turn, ConversationTurnReservation)
    call = start(store, created.session_id, turn)
    with patch.object(store, "_clock", side_effect=[now, created.expires_at]), patch(
        "app.sessions.conversation.uuid4", side_effect=AssertionError("must not allocate")):
        with pytest.raises(TurnHistoryUnavailable) as error:
            store.record_result(created.session_id, call, candidate())
    assert error.value.kind == "expired"
    assert store.history(created.session_id) == ()


def output_text[ArtifactT](execution: ToolExecution[ArtifactT]) -> str:
    assert isinstance(execution.output, str)
    return execution.output
