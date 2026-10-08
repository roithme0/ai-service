import asyncio
import json
from datetime import timedelta

import pytest

from app.agents.generation_history import record_generation_item, record_generation_response
from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.models.conversation import ConversationSessionSettings, ConversationTurnReservation
from app.sessions.session_store import ConversationSessionStore
from app.sessions.models.history import CallRecord, ExecutionReportRecord, ExecutionStartedRecord, MessageRecord, ContinuationRecord, TerminalRecord, ToolResultRecord
from app.agents.history_projection import model_input
from app.sessions.message_projection import completed_text_messages
from app.agents.model_turn_execution import ModelTurnStrategy
from reserved_turn import execute_reserved_turn
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.models.tools import LocalToolSource
from app.sessions.models.execution import ToolExecution
from app.sessions.models.timeline import TimelineIntermediateMessage, TimelineMessage


def call_response(*calls: AgenticToolCall) -> AgenticGenerationResponse:
    return AgenticGenerationResponse((
        {"type": "reasoning", "id": "reasoning", "summary": [], "encrypted_content": "opaque"},
        *({"type": "function_call", "call_id": call.call_id, "name": call.name,
           "arguments": call.arguments} for call in calls),
    ), calls, None)


def final_response(text: str) -> AgenticGenerationResponse:
    return AgenticGenerationResponse(({"type": "message", "id": "reply", "role": "assistant", "phase": "final_answer",
        "content": [{"type": "output_text", "text": text, "annotations": []}]},), (), text)


@pytest.mark.parametrize("ending", ["final", "failure", "limit"])
def test_commentary_only_continues_and_remains_visible_without_becoming_final(ending: str) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    commentary = dict(final_response("I will check.").output_items[0], phase="commentary")
    requests: list[AgenticGenerationRequest] = []

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            if len(requests) == 1 or ending == "limit":
                return AgenticGenerationResponse((commentary,), (), "I will check.")
            assert request.input_items[-1] == commentary
            if ending == "failure":
                raise RuntimeError("failed after commentary")
            update = dict(final_response("Check complete.").output_items[0], phase="commentary")
            final = dict(final_response("The answer is 42.").output_items[0], phase="final_answer")
            return AgenticGenerationResponse((update, final), (), "Check complete.The answer is 42.")

    strategy = ModelTurnStrategy(store, Generator(), lambda context: context, (), max_provider_responses=2)
    store.append_user_message(session_id, "Check")
    result = asyncio.run(execute_reserved_turn(store, strategy, session_id))
    assert len(requests) == 2
    assert result.kind == ("completed" if ending == "final" else "generation_failed")
    history = store.history(session_id)
    read = store.read(session_id)
    updates = [item for item in read.snapshot.timeline if isinstance(item, TimelineIntermediateMessage)]
    assert updates[0].text == "I will check."
    assert len({item.id for item in updates}) == len(updates)
    assert commentary in model_input(history)
    if ending == "final":
        assert result.text == "The answer is 42."
        assert [message.text for message in completed_text_messages(history)] == ["Check", "The answer is 42."]
        assert [item.kind for item in read.snapshot.timeline] == ["message", "intermediate", "intermediate", "message"]
        assert isinstance(read.snapshot.timeline[-1], TimelineMessage)
    else:
        assert result.text is None
        assert [message.text for message in completed_text_messages(history)] == ["Check"]
        assert read.snapshot.timeline[-1].kind == "failure"


@pytest.mark.parametrize("failure", [False, True])
def test_later_turn_replays_exact_domain_result_and_context_without_tool_execution(failure: bool) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    requests: list[AgenticGenerationRequest] = []
    invocations: list[ToolInvocation] = []
    output = '{"proposal_id": "domain-123", "kind": "proposed"}'

    def execute(invocation: ToolInvocation) -> ToolExecution[str]:
        history = store.history(session_id)
        assert isinstance(history[-1], ExecutionStartedRecord)
        assert isinstance(history[-2], CallRecord)
        assert not any(isinstance(record, ToolResultRecord) for record in history)
        invocations.append(invocation)
        return ToolExecution(output)

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            if len(requests) == 1:
                return call_response(AgenticToolCall("same-provider-id", "propose", '{"name":"Meal"}'))
            if len(requests) == 2:
                assert request.input_items[-1]["output"] == output
                if failure:
                    raise RuntimeError("generation failed after domain success")
                return final_response("Proposed")
            assert len(invocations) == 1
            assert request.input_items[0] == {"role": "user", "content": "initial"}
            replay = request.input_items[1:]
            assert replay[0] == {"role": "user", "content": "first"}
            assert replay[1]["encrypted_content"] == "opaque"
            assert replay[2]["arguments"] == '{"name":"Meal"}'
            assert replay[3]["output"] == output
            assert replay[-1] == {"role": "user", "content": "save domain-123"}
            assert len(replay) == (5 if failure else 6)
            if not failure:
                assert replay[4]["type"] == "message"
            return final_response("Saved")

    strategy = ModelTurnStrategy(store, Generator(), lambda context: context, (LocalToolSource((
        RegisteredTool("propose", {"type": "function", "name": "propose"}, execute),)),))
    store.append_user_message(session_id, "first")
    first = asyncio.run(execute_reserved_turn(store, strategy, session_id))
    assert first.kind == ("generation_failed" if failure else "completed")
    history = store.history(session_id)
    assert isinstance(history[-1], TerminalRecord)
    assert history[-1].kind == first.kind
    assert len([record for record in history if isinstance(record, ToolResultRecord)]) == 1
    assert len([record for record in history if isinstance(record, MessageRecord)]) == (1 if failure else 2)
    if failure:
        assert asyncio.run(execute_reserved_turn(store, strategy, session_id)) == first
        assert len(requests) == 2
    store.append_user_message(session_id, "save domain-123")
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == "completed"
    assert len(invocations) == 1
    assert len([item for item in model_input(store.history(session_id)) if item.get("type") == "message"]) == (1 if failure else 2)


@pytest.mark.parametrize("cancel", [False, True])
def test_mixed_exchange_replays_unknown_and_not_executed_reports_without_fabricated_results(cancel: bool) -> None:
    async def exercise() -> None:
        store = ConversationSessionStore[str, str](timedelta(minutes=90))
        session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
        entered = asyncio.Event()
        executions: list[str] = []
        requests: list[AgenticGenerationRequest] = []

        async def execute(invocation: ToolInvocation) -> ToolExecution[str]:
            executions.append(invocation.arguments)
            if invocation.arguments == "first":
                return ToolExecution('{"kind":"tool_failed","detail":"actual domain response"}')
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise RuntimeError("no confirmed outcome")

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) == 1:
                    return call_response(*(AgenticToolCall(str(index), "mutate", args)
                                           for index, args in enumerate(("first", "second", "third"))))
                assert executions == ["first", "second"]
                assert [item["call_id"] for item in request.input_items if item.get("type") == "function_call"] == ["0", "1", "2"]
                outputs = [item for item in request.input_items if item.get("type") == "function_call_output"]
                assert json.loads(str(outputs[0]["output"]))["kind"] == "tool_failed"
                unknown = json.loads(str(outputs[1]["output"]))
                not_started = json.loads(str(outputs[2]["output"]))
                assert unknown["state"] == "outcome_unknown"
                assert "may have completed" in unknown["detail"]
                assert "Investigate before repeating" in unknown["detail"]
                assert unknown["provenance"] == not_started["provenance"] == "service"
                assert not_started["state"] == "not_executed"
                return final_response("Investigate")

        strategy = ModelTurnStrategy(store, Generator(), lambda context: context, (LocalToolSource((
            RegisteredTool("mutate", {"type": "function", "name": "mutate"}, execute),)),))
        store.append_user_message(session_id, "first message")
        task = asyncio.create_task(execute_reserved_turn(store, strategy, session_id))
        await entered.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).kind == "generation_failed"
        history = store.history(session_id)
        calls = [record for record in history if isinstance(record, CallRecord)]
        assert len(calls) == 3
        assert len({record.execution_id for record in calls}) == 3
        assert len([record for record in history if isinstance(record, ToolResultRecord)]) == 1
        reports = [record for record in history if isinstance(record, ExecutionReportRecord)]
        assert [record.state for record in reports] == ["outcome_unknown", "not_executed"]
        assert reports[0].execution_id == calls[1].execution_id
        assert reports[1].execution_id == calls[2].execution_id
        store.append_user_message(session_id, "investigate")
        assert (await execute_reserved_turn(store, strategy, session_id)).kind == "completed"
        assert executions == ["first", "second"]

    asyncio.run(exercise())


@pytest.mark.parametrize("invalid_text", ["", "x" * 16001])
def test_invalid_final_output_is_not_retained_or_replayed(invalid_text: str) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    requests: list[AgenticGenerationRequest] = []

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            return final_response(invalid_text if len(requests) == 1 else "Recovered")

    strategy = ModelTurnStrategy(store, Generator(), lambda context: context, ())
    store.append_user_message(session_id, "first")
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == "generation_failed"
    assert not any(isinstance(record, MessageRecord) and record.kind != "user"
                   for record in store.history(session_id))
    store.append_user_message(session_id, "recover")
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == "completed"
    assert requests[-1].input_items == ({"role": "user", "content": "initial"},
        {"role": "user", "content": "first"}, {"role": "user", "content": "recover"})


def test_final_message_with_tool_executes_tool_before_completion() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    requests: list[AgenticGenerationRequest] = []

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            if len(requests) == 1:
                response = call_response(AgenticToolCall("unknown", "unknown", "{}"))
                return AgenticGenerationResponse((*final_response("Working").output_items, *response.output_items), response.tool_calls, "Working")
            return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "Done"},), (), "Done")

    strategy = ModelTurnStrategy(store, Generator(), lambda context: context, ())
    store.append_user_message(session_id, "first")
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == "completed"
    history = store.history(session_id)
    assert len(requests) == 1
    assert store.read(session_id).snapshot.session.messages[-1].text == "Working"
    result = next(record for record in history if isinstance(record, ToolResultRecord))
    assert json.loads(result.output) == {"kind": "rejected", "reason": "unknown_tool"}
    assert not any(isinstance(record, ExecutionStartedRecord) for record in history)


def test_individual_records_preserve_provider_order_and_derive_both_message_views() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "first")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    call = AgenticToolCall("call-1", "sample", "{}")
    call_item = {"type": "function_call", "id": "provider-call", "call_id": call.call_id,
                 "name": call.name, "arguments": call.arguments}
    intermediate = dict(final_response("Working").output_items[0], phase="commentary")
    reasoning = {"type": "reasoning", "encrypted_content": "opaque", "summary": []}
    response = AgenticGenerationResponse((intermediate, reasoning, call_item), (call,), "Working")
    recorded = record_generation_response(store, session_id, reservation.turn_id, response)[0]
    assert (recorded.call_id, recorded.name, recorded.arguments) == (call.call_id, call.name, call.arguments)
    store.start_execution(session_id, recorded)
    store.record_result(session_id, recorded, ToolExecution("result"))
    first_final = dict(final_response("Hello ").output_items[0], phase="final_answer")
    second_final = dict(final_response("world").output_items[0], id="reply-2", phase="final_answer")
    record_generation_response(store, session_id, reservation.turn_id,
        AgenticGenerationResponse((first_final, second_final), (), "Hello world"))
    assert len(store.read(session_id).snapshot.session.messages) == 1
    store.complete_turn(session_id, reservation, "completed", "Hello world")
    history = store.history(session_id)
    assert [type(record) for record in history] == [
        MessageRecord, MessageRecord, ContinuationRecord, CallRecord, ExecutionStartedRecord,
        ToolResultRecord, MessageRecord, MessageRecord, TerminalRecord,
    ]
    assert model_input(history) == (
        {"role": "user", "content": "first"}, intermediate, reasoning, call_item,
        {"type": "function_call_output", "call_id": call.call_id, "output": "result"},
        first_final, second_final,
    )
    messages = completed_text_messages(history)
    assert [(message.role, message.text) for message in messages] == [
        ("user", "first"), ("assistant", "Hello "),
    ]
    assert messages[1].turn_id == reservation.turn_id
    assert store.read(session_id).snapshot.session.messages == messages


def test_history_drives_revision_terminal_status_and_repeated_failure_response() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("initial", ConversationSessionSettings(2), owner="test:user").session_id
    assert store.read(session_id).snapshot.session.revision == 0
    store.append_user_message(session_id, "first")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    assert reservation.snapshot.revision == 1
    response = call_response(AgenticToolCall("call", "sample", "{}"))
    intermediate = dict(final_response("Working").output_items[0], phase="commentary")
    call = record_generation_response(store, session_id, reservation.turn_id,
        AgenticGenerationResponse((intermediate, *response.output_items), response.tool_calls, "Working"))[0]
    store.start_execution(session_id, call)
    store.record_result(session_id, call, ToolExecution("result"))
    record_generation_response(store, session_id, reservation.turn_id, final_response("Done"))
    assert store.read(session_id).snapshot.session.revision == 1
    completed = store.complete_turn(session_id, reservation, "completed", "Done")
    read = store.read(session_id).snapshot
    assert read.session.revision == 2
    assert read.session.messages[-1].text == completed.text == "Done"
    assert read.terminal_turn_id == reservation.turn_id
    assert read.terminal_turn_kind == "completed"
    store.append_user_message(session_id, "second")
    assert store.read(session_id).snapshot.terminal_turn_id is None
    next_turn = store.reserve_turn(session_id)
    assert isinstance(next_turn, ConversationTurnReservation)
    failed = store.fail_turn(session_id, next_turn)
    history = store.history(session_id)
    assert store.reserve_turn(session_id) == failed
    assert store.history(session_id) == history
    assert store.read(session_id).snapshot.session.revision == 3
    store.append_user_message(session_id, "third")
    third = store.reserve_turn(session_id)
    assert isinstance(third, ConversationTurnReservation)
    assert third.snapshot.revision == 4
    assert third.turn_id != next_turn.turn_id


@pytest.mark.parametrize("phase", [None, "commentary", "final_answer"])
@pytest.mark.parametrize("fail", [False, True])
def test_message_phase_is_immutable_through_turn_outcome(phase: str | None, fail: bool) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("Context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Run")
    snapshots: list[tuple[object, ...]] = []
    supplied = dict(final_response("First").output_items[0], phase=phase)

    class Generator:
        count = 0

        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            self.count += 1
            if self.count == 1:
                response = AgenticGenerationResponse((supplied, {"type": "function_call", "call_id": "unknown",
                    "name": "unknown", "arguments": "{}"}), (AgenticToolCall("unknown", "unknown", "{}"),), "First")
                assert request.on_output_item is not None
                for item in response.output_items:
                    request.on_output_item(item)
                snapshots.append(store.history(session_id))
                if fail:
                    raise RuntimeError("interrupted")
                return response
            return final_response("Done")

    strategy = ModelTurnStrategy(store, Generator(), str, ())
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)).kind == ("generation_failed" if fail else "completed")
    history = store.history(session_id)
    assert history[:len(snapshots[0])] == snapshots[0]
    first = history[1]
    assert isinstance(first, MessageRecord)
    assert first.item is not None
    assert first.item.get("phase") == phase
    if phase is None:
        assert "phase" not in first.item and first.kind == "unspecified"
    elif phase == "final_answer":
        assert first.kind == "final"
    assert first.item in model_input(history)
    read = store.read(session_id).snapshot
    assert read.session.revision == (1 if fail else 2)
    visible = [item for item in read.timeline if isinstance(item, (TimelineMessage, TimelineIntermediateMessage))]
    assert any(item.text == "First" for item in visible)
    if phase is None:
        assert isinstance(next(item for item in visible if item.text == "First"), TimelineMessage)
    if not fail:
        assert read.session.messages[-1].text == ("First" if phase == "final_answer" else "Done")


@pytest.mark.parametrize("phase", [None, "commentary", "final_answer"])
@pytest.mark.parametrize("text", [" ", "x" * 16001])
def test_invalid_message_item_fails_before_retention(phase: str | None, text: str) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("Context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Run")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    valid = dict(final_response("Working").output_items[0], phase="commentary")
    record_generation_item(store, session_id, reservation.turn_id, valid)
    before = store.history(session_id)
    with pytest.raises(ValueError, match="assistant message"):
        record_generation_item(store, session_id, reservation.turn_id,
            dict(final_response(text).output_items[0], phase=phase))
    assert store.history(session_id) == before
    assert model_input(before)[-1] == valid


@pytest.mark.parametrize("output", ["phaseless", "null", "commentary", "reasoning", "empty", "text_only"])
def test_response_limit_requires_explicit_final_and_replays_every_completed_item(output: str) -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("Context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Run")
    requests: list[AgenticGenerationRequest] = []
    item: dict[str, object] = {"type": "message", "role": "assistant", "content": "Still working"}
    if output == "null":
        item["phase"] = None
    elif output == "commentary":
        item["phase"] = "commentary"
    elif output == "reasoning":
        item = {"type": "reasoning", "summary": [], "encrypted_content": "opaque"}
    items = () if output in ("empty", "text_only") else (item,)

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            requests.append(request)
            assert request.input_items[2:] == items * (len(requests) - 1)
            return AgenticGenerationResponse(items, (), "text-only cannot finish" if output == "text_only" else None)

    strategy = ModelTurnStrategy(store, Generator(), str, (), max_provider_responses=3)
    result = asyncio.run(execute_reserved_turn(store, strategy, session_id))
    assert result.kind == "generation_failed"
    assert len(requests) == 3
    history = store.history(session_id)
    retained = tuple({key: value for key, value in item.items() if key != "phase" or value is not None}
                     for item in items) * 3
    assert model_input(history)[1:] == retained
    assert asyncio.run(execute_reserved_turn(store, strategy, session_id)) == result
    assert store.history(session_id) == history
    assert len(requests) == 3


def test_multiple_final_messages_select_first_without_combining_or_aggregate_validation() -> None:
    store = ConversationSessionStore[str, str](timedelta(minutes=90))
    session_id = store.create("Context", ConversationSessionSettings(2), owner="test:user").session_id
    store.append_user_message(session_id, "Run")
    first = final_response("a" * 10000).output_items[0]
    second = dict(final_response("b" * 10000).output_items[0], id="second")
    calls = 0

    class Generator:
        async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
            nonlocal calls
            calls += 1
            return AgenticGenerationResponse((first, second), (), "ignored aggregate")

    result = asyncio.run(execute_reserved_turn(store, ModelTurnStrategy(store, Generator(), str, ()), session_id))
    assert result.kind == "completed" and result.text == "a" * 10000
    assert calls == 1
    assert model_input(store.history(session_id))[1:] == (first, second)
    assert [message.text for message in store.read(session_id).snapshot.session.messages] == ["Run", "a" * 10000]
