import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

import httpx
from openai import AsyncOpenAI

from app.agents.openai_agentic_generation import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OpenAIAgenticGenerator,
)
from typing import Never

from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.models.history import CallRecord, ExecutionReportRecord, MessageRecord, ToolResultRecord
from app.agents.history_projection import model_input
from app.sessions.models.conversation import ConversationSessionSettings
from app.sessions.session_store import ConversationSessionStore
from app.agents.model_turn_execution import ModelTurnStrategy
from reserved_turn import execute_reserved_turn
from app.agents.tool_turns import run_tool_turn
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.models.tools import LocalToolSource
from app.sessions.models.execution import ToolExecution
from tool_turn_recorder import ToolTurnRecorder


def response_payload(output: list[dict[str, object]], status: str = "completed") -> dict[str, object]:
    return {"id": "resp_1", "object": "response", "created_at": 1,
            "model": "gpt-5.6-sol", "status": status, "output": output, "error": None}


def response_events(output: list[dict[str, object]], ending: str = "response.completed") -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {"type": "response.created", "response": response_payload([], "in_progress")},
    ]
    for index, item in enumerate(output):
        initial = dict(item)
        if item["type"] == "function_call":
            initial["arguments"] = ""
        elif item["type"] == "message":
            initial["content"] = []
        events.append({"type": "response.output_item.added", "output_index": index, "item": initial})
        if item["type"] == "function_call":
            arguments = item["arguments"]
            assert isinstance(arguments, str)
            for fragment in (arguments[:2], arguments[2:]):
                events.append({"type": "response.function_call_arguments.delta", "output_index": index,
                               "item_id": item["id"], "delta": fragment})
        elif item["type"] == "message":
            content = item["content"]
            assert isinstance(content, list)
            for content_index, part in enumerate(content):
                assert isinstance(part, dict)
                text = part["text"]
                assert isinstance(text, str)
                events.append({"type": "response.content_part.added", "output_index": index,
                               "content_index": content_index, "item_id": item["id"],
                               "part": dict(part, text="")})
                for fragment in (text[:2], text[2:]):
                    events.append({"type": "response.output_text.delta", "output_index": index,
                                   "content_index": content_index, "item_id": item["id"],
                                   "delta": fragment, "logprobs": []})
        events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    if ending == "error":
        events.append({"type": "error", "code": "server_error", "message": "failure", "param": None})
    elif ending != "missing":
        status = {"response.failed": "failed", "response.incomplete": "incomplete"}.get(ending, "completed")
        events.append({"type": ending, "response": response_payload(output, status)})
    return [dict(event, sequence_number=index) for index, event in enumerate(events)]


class EventStream(httpx.AsyncByteStream):
    def __init__(self, events: list[dict[str, object]], *, delay: float = 0,
                 disconnect: bool = False, repeat: bool = False) -> None:
        self.events = events
        self.delay = delay
        self.disconnect = disconnect
        self.repeat = repeat
        self.closed = False
        self.started = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        for event in self.events:
            await asyncio.sleep(self.delay)
            yield ("data: " + json.dumps(event) + "\n\n").encode()
        if self.disconnect:
            raise httpx.ReadError("disconnected")
        while self.repeat:
            await asyncio.sleep(self.delay)
            yield ("data: " + json.dumps({"type": "response.output_text.delta", "output_index": 0,
                                        "content_index": 0, "item_id": "msg_final_answer",
                                        "delta": ".", "logprobs": [], "sequence_number": 99}) + "\n\n").encode()

    async def aclose(self) -> None:
        self.closed = True


def message(text: str, phase: str = "final_answer") -> dict[str, object]:
    return {"id": "msg_" + phase, "type": "message", "role": "assistant", "status": "completed",
            "phase": phase, "content": [{"type": "output_text", "text": text, "annotations": []}]}


def function_call() -> dict[str, object]:
    return {"id": "fc_1", "type": "function_call", "call_id": "call_1",
            "name": "sample", "arguments": "{}", "status": "completed"}


def test_openai_replays_function_call_and_result_without_storage() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload: object = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        if len(requests) == 1:
            output = [{"id": "rs_1", "type": "reasoning", "summary": [],
                       "encrypted_content": "opaque-reasoning", "status": "completed"},
                      {"id": "fc_1", "type": "function_call", "call_id": "call_1",
                       "name": "sample", "arguments": "not-json", "status": "completed"}]
        else:
            assert all("status" not in item for item in payload["input"])
            output = [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed", "phase": "final_answer",
                       "content": [{"type": "output_text", "text": "That call failed.",
                                    "annotations": []}]}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              stream=EventStream(response_events(output)))

    invoked = False
    recorder = ToolTurnRecorder[Never]()

    def execute(call: ToolInvocation) -> ToolExecution[Never]:
        nonlocal invoked
        try:
            json.loads(call.arguments)
        except json.JSONDecodeError:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        invoked = True
        return ToolExecution("accepted")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test-key", http_client=http_client, max_retries=0) as client:
                result = await run_tool_turn(
                    OpenAIAgenticGenerator("gpt-5.6-sol", client),
                    ({"role": "user", "content": "Try it"},), "Caller context", "Instructions",
                    (LocalToolSource((RegisteredTool("sample", {
                        "type": "function", "name": "sample", "parameters": {"type": "object"},
                    }, execute),)),), 6, 3, 8, record_item=recorder.record_item,
                    start_execution=recorder.start_execution, record_result=recorder.record_result,
                )
                assert result.kind == "completed"
                assert result.text == "That call failed."

    asyncio.run(run())
    assert not invoked
    assert recorder.items[-1].item["phase"] == "final_answer"
    assert len(requests) == 2
    assert all(request["stream"] is True for request in requests)
    assert all(request["store"] is False and request["parallel_tool_calls"] is True for request in requests)
    assert all(request["max_output_tokens"] == OPENAI_MAX_OUTPUT_TOKENS for request in requests)
    assert all(request["include"] == ["reasoning.encrypted_content"] for request in requests)
    assert requests[0]["input"] == [
        {"role": "user", "content": "Caller context"},
        {"role": "user", "content": "Try it"},
    ]
    replay = requests[1]["input"]
    assert isinstance(replay, list)
    assert replay[2] == {"id": "rs_1", "type": "reasoning", "summary": [],
                         "encrypted_content": "opaque-reasoning"}
    assert replay[3] == {"id": "fc_1", "type": "function_call", "call_id": "call_1",
                         "name": "sample", "arguments": "not-json"}
    assert replay[4]["type"] == "function_call_output"
    assert replay[4]["call_id"] == "call_1"
    assert json.loads(replay[4]["output"]) == {"kind": "rejected", "reason": "invalid_arguments"}


@pytest.mark.parametrize("ending", ["response.completed", "response.incomplete"])
def test_multi_call_stream_executes_sequentially_and_replays_all_results(ending: str) -> None:
    calls = [function_call(), dict(function_call(), id="fc_2", call_id="call_2", arguments='{"value":2}')]
    requests: list[dict[str, object]] = []
    bodies: list[EventStream] = []
    executions: list[tuple[str, str]] = []
    recorder = ToolTurnRecorder[Never]()

    def respond(request: httpx.Request) -> httpx.Response:
        payload: object = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        body = EventStream(response_events(calls, ending) if len(requests) == 1
                           else response_events([message("Finished.")]))
        bodies.append(body)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    async def execute(call: ToolInvocation) -> ToolExecution[Never]:
        assert bodies[0].closed
        assert len(recorder.calls) == 2
        assert len(executions) % 2 == 0
        executions.append(("started", call.arguments))
        await asyncio.sleep(0)
        executions.append(("finished", call.arguments))
        return ToolExecution("result: " + call.arguments)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                turn = run_tool_turn(
                    OpenAIAgenticGenerator("model", client), (), "Context", "Instructions",
                    (LocalToolSource((RegisteredTool("sample", {
                        "type": "function", "name": "sample", "parameters": {"type": "object"},
                    }, execute),)),), 2, None, 2,
                    record_item=recorder.record_item, start_execution=recorder.start_execution,
                    record_result=recorder.record_result,
                )
                if ending == "response.incomplete":
                    with pytest.raises(ValueError, match="stream failed"):
                        await turn
                else:
                    result = await turn
                    assert result.kind == "completed" and result.text == "Finished."

    asyncio.run(run())
    assert all(request["parallel_tool_calls"] is True for request in requests)
    assert [call.call_id for call in recorder.calls] == ["call_1", "call_2"]
    assert all(body.closed for body in bodies)
    if ending == "response.incomplete":
        assert len(requests) == 1
        assert executions == recorder.started == recorder.results == []
    else:
        assert len(requests) == 2
        assert executions == [(state, arguments) for arguments in ("{}", '{"value":2}')
                              for state in ("started", "finished")]
        assert requests[1]["input"] == [
            {"role": "user", "content": "Context"},
            *({key: value for key, value in call.items() if key != "status"} for call in calls),
            *({"type": "function_call_output", "call_id": call["call_id"],
               "output": "result: " + str(call["arguments"])} for call in calls),
        ]


@pytest.mark.parametrize("allow_multiple_tool_calls", [False, True])
def test_fragmented_messages_preserve_order_and_phases(
    monkeypatch: pytest.MonkeyPatch, allow_multiple_tool_calls: bool,
) -> None:
    monkeypatch.setattr("app.agents.config.ALLOW_MULTIPLE_TOOL_CALLS", allow_multiple_tool_calls)
    output = [message("Checking.", "commentary"), message("Finished.")]
    body = EventStream(response_events(output))

    def respond(request: httpx.Request) -> httpx.Response:
        payload: object = json.loads(request.content)
        assert isinstance(payload, dict)
        assert payload["parallel_tool_calls"] is allow_multiple_tool_calls
        return httpx.Response(200, stream=body)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                result = await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(
                    AgenticGenerationRequest((), "Instructions", ()))
                assert result.text == "Finished."
                assert [item["phase"] for item in result.output_items] == ["commentary", "final_answer"]
                assert [item["id"] for item in result.output_items] == [item["id"] for item in output]
                assert result.tool_calls == ()
        assert body.closed

    asyncio.run(run())


@pytest.mark.parametrize("ending", ["response.failed", "response.incomplete", "error", "missing", "disconnect"])
@pytest.mark.parametrize("prior_success", [False, True])
def test_failed_stream_retains_complete_calls_without_executing_them(ending: str, prior_success: bool) -> None:
    bodies: list[EventStream] = []
    invocations: list[ToolInvocation] = []

    def respond(request: httpx.Request) -> httpx.Response:
        first_success = prior_success and not bodies
        events = response_events([message("Partial.", "commentary"), function_call()],
                                 "response.completed" if first_success else ("missing" if ending == "disconnect" else ending))
        body = EventStream(events, disconnect=ending == "disconnect" and not first_success)
        bodies.append(body)
        return httpx.Response(200, stream=body)

    def execute(call: ToolInvocation) -> ToolExecution[ArtifactCandidate[str]]:
        assert bodies[0].closed
        invocations.append(call)
        return ToolExecution(ArtifactToolOutput("presented"), ArtifactCandidate("example", "retained payload"))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                store = ConversationSessionStore[str, str](timedelta(minutes=90))
                session_id = store.create("Context", ConversationSessionSettings(20), owner="test:user").session_id
                store.append_user_message(session_id, "Run")
                strategy = ModelTurnStrategy(store, OpenAIAgenticGenerator("gpt-5.6-sol", client),
                    lambda context: context, (LocalToolSource((RegisteredTool("sample",
                    {"type": "function", "name": "sample"}, execute),)),))
                assert (await execute_reserved_turn(store, strategy, session_id)).kind == "generation_failed"
                history = store.history(session_id)
                assert len([record for record in history if isinstance(record, CallRecord)]) == 1 + int(prior_success)
                reports = [record for record in history if isinstance(record, ExecutionReportRecord)]
                assert len(reports) == 1 and reports[0].state == "not_executed"
                assert len([record for record in history if isinstance(record, MessageRecord) and record.kind == "intermediate"]) == 1 + int(prior_success)
                results = [record for record in history if isinstance(record, ToolResultRecord)]
                assert len(results) == int(prior_success)
                replay = model_input(history)
                if prior_success:
                    assert any(item.get("output") == results[0].output for item in replay)
                    assert store.read(session_id).snapshot.artifacts[0].payload == "retained payload"
                else:
                    assert replay[0] == {"role": "user", "content": "Run"}
                    assert replay[-1]["call_id"] == "call_1"
                    assert json.loads(str(replay[-1]["output"]))["state"] == "not_executed"
                assert (await execute_reserved_turn(store, strategy, session_id)).kind == "generation_failed"
        assert len(bodies) == 1 + int(prior_success)
        assert len(invocations) == int(prior_success)
        assert all(body.closed for body in bodies)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_and_cancellation_close_stream_without_restart(monkeypatch: pytest.MonkeyPatch, cancel: bool) -> None:
    monkeypatch.setattr("app.agents.openai_agentic_generation.OPENAI_REQUEST_TIMEOUT_SECONDS", 0.05)
    body = EventStream(response_events([message("Partial.")], "missing"), delay=0.005, repeat=True)
    requests = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, stream=body)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                task = asyncio.create_task(OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(
                    AgenticGenerationRequest((), "Instructions", ())))
                await body.started.wait()
                if cancel:
                    task.cancel()
                with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                    await asyncio.wait_for(task, 1)
        assert body.closed
        assert requests == 1

    asyncio.run(run())


@pytest.mark.parametrize("mismatch", [None, "identity", "summary", "text", "arguments", "order", "missing"])
def test_reasoning_ciphertext_changes_do_not_mask_output_mismatches(mismatch: str | None) -> None:
    output: list[dict[str, object]] = [
        {"id": "rs_1", "type": "reasoning", "status": "completed", "summary": [],
         "encrypted_content": "item-completion-token"},
        message("I will adjust the eggs.", "commentary"),
        function_call(),
    ]
    events = response_events(output)
    final_output: list[dict[str, object]] = json.loads(json.dumps(output))
    final_output[0]["encrypted_content"] = "response-completion-token"
    if mismatch == "identity":
        final_output[0]["id"] = "rs_other"
    elif mismatch == "summary":
        final_output[0]["summary"] = [{"type": "summary_text", "text": "Different summary"}]
    elif mismatch == "text":
        final_output[1] = message("Different message.", "commentary")
    elif mismatch == "arguments":
        final_output[2]["arguments"] = '{"eggs": 4}'
    elif mismatch == "order":
        final_output.reverse()
    elif mismatch == "missing":
        final_output.pop()
    final = events[-1]["response"]
    assert isinstance(final, dict)
    final["output"] = final_output
    body = EventStream(events)
    retained: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body)
        )) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                request = AgenticGenerationRequest((), "Instructions", (), on_output_item=retained.append)
                if mismatch is not None:
                    with pytest.raises(ValueError, match="disagrees with recorded items"):
                        await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(request)
                else:
                    result = await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(request)
                    assert result.output_items == tuple(retained)
                    assert result.output_items[0]["encrypted_content"] == "item-completion-token"
                    assert result.tool_calls[0].arguments == "{}"
        assert body.closed

    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["status", "error", "output", "malformed", "late_error"])
def test_completed_event_does_not_bypass_failure_or_output_validation(invalid: str) -> None:
    events = response_events([message("Finished.")])
    final = events[-1]["response"]
    assert isinstance(final, dict)
    if invalid == "status":
        final["status"] = "incomplete"
    elif invalid == "error":
        final["error"] = {"code": "server_error", "message": "failure"}
    elif invalid == "output":
        final["output"] = [{"type": "function_call", "id": "fc_1", "call_id": "",
                            "name": "sample", "arguments": "{}"}]
    elif invalid == "malformed":
        events = [{"type": "response.output_text.delta", "output_index": 0,
                   "content_index": 0, "item_id": "missing", "delta": "text"}]
    else:
        events.append({"type": "error", "code": "server_error", "message": "failure", "param": None})
    body = EventStream(events)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body)
        )) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises((ValueError, RuntimeError)):
                    await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(
                        AgenticGenerationRequest((), "Instructions", ()))
        assert body.closed

    asyncio.run(run())


def test_deadline_includes_stream_establishment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.openai_agentic_generation.OPENAI_REQUEST_TIMEOUT_SECONDS", 0.01)
    requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        await asyncio.sleep(1)
        raise AssertionError("establishment must time out")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises(TimeoutError):
                    await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(
                        AgenticGenerationRequest((), "Instructions", ()))
        assert requests == 1

    asyncio.run(run())


class PausedItemStream(EventStream):
    def __init__(self, events: list[dict[str, object]]) -> None:
        super().__init__(events)
        self.paused = (asyncio.Event(), asyncio.Event())
        self.release = (asyncio.Event(), asyncio.Event())

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.started.set()
        completed_items = 0
        for event in self.events:
            yield ("data: " + json.dumps(event) + "\n\n").encode()
            if event["type"] == "response.output_item.done" and completed_items < 2:
                self.paused[completed_items].set()
                await self.release[completed_items].wait()
                completed_items += 1


@pytest.mark.parametrize("ending", ["success", "missing", "cancel", "timeout"])
def test_completed_items_are_retained_before_stream_finishes_and_replayed(
    monkeypatch: pytest.MonkeyPatch, ending: str,
) -> None:
    from app.sessions.models.history import ContinuationRecord, TerminalRecord
    output = [message("Checking.", "commentary"), function_call(),
              {"id": "rs_1", "type": "reasoning", "status": "completed", "summary": [],
               "encrypted_content": "opaque"}]
    body = PausedItemStream(response_events(output, "response.completed" if ending == "success" else "missing"))
    bodies: list[EventStream] = []
    requests: list[dict[str, object]] = []
    invocations: list[ToolInvocation] = []
    if ending == "timeout":
        monkeypatch.setattr("app.agents.openai_agentic_generation.OPENAI_REQUEST_TIMEOUT_SECONDS", 0.05)

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        stream = body if not bodies else EventStream(response_events([message("Done.")]))
        bodies.append(stream)
        return httpx.Response(200, stream=stream)

    def execute(call: ToolInvocation) -> ToolExecution[ArtifactCandidate[str]]:
        assert body.closed
        invocations.append(call)
        return ToolExecution("actual result")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                store = ConversationSessionStore[str, str](timedelta(minutes=90))
                session_id = store.create("Context", ConversationSessionSettings(20), owner="test:user").session_id
                store.append_user_message(session_id, "Run")
                strategy = ModelTurnStrategy(store, OpenAIAgenticGenerator("model", client), str,
                    (LocalToolSource((RegisteredTool("sample", {"type": "function", "name": "sample"}, execute),)),))
                task = asyncio.create_task(execute_reserved_turn(store, strategy, session_id))
                await asyncio.wait_for(body.paused[0].wait(), 1)
                first = store.history(session_id)
                assert len(first) == 2 and isinstance(first[-1], MessageRecord)
                assert first[-1].item["phase"] == "commentary"
                assert store.read(session_id).snapshot.timeline[-1].kind == "intermediate"
                body.release[0].set()
                await asyncio.wait_for(body.paused[1].wait(), 1)
                recorded = store.history(session_id)
                assert isinstance(recorded[-1], CallRecord) and not invocations
                if ending == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                elif ending == "timeout":
                    assert (await asyncio.wait_for(task, 1)).kind == "generation_failed"
                else:
                    body.release[1].set()
                    assert (await asyncio.wait_for(task, 1)).kind == ("completed" if ending == "success" else "generation_failed")
                history = store.history(session_id)
                assert history[:len(recorded)] == recorded
                assert len([record for record in history if isinstance(record, CallRecord)]) == 1
                assert len([record for record in history if isinstance(record, TerminalRecord)]) == 1
                assert body.closed
                if ending == "success":
                    assert len(invocations) == 1
                    assert any(isinstance(record, ContinuationRecord) for record in history)
                    assert requests[-1]["input"][-1] == {"type": "function_call_output", "call_id": "call_1", "output": "actual result"}
                else:
                    assert not invocations
                    reports = [record for record in history if isinstance(record, ExecutionReportRecord)]
                    assert len(reports) == 1 and reports[0].state == "not_executed"
                    assert (await execute_reserved_turn(store, strategy, session_id)).kind == "generation_failed"
                    assert store.history(session_id) == history and len(requests) == 1
                    store.append_user_message(session_id, "Recover")
                    assert (await execute_reserved_turn(store, strategy, session_id)).kind == "completed"
                    assert requests[-1]["input"][1:-1] == list(model_input(history))
                    assert not invocations
    asyncio.run(run())


@pytest.mark.parametrize("invalid", ["duplicate", "incomplete", "empty_content", "bad_content", "disagreement", "partial"])
def test_bad_or_partial_item_never_rewrites_prior_complete_item(invalid: str) -> None:
    first = message("Retained.", "commentary")
    second = message("Second.")
    events = response_events([first, second])
    if invalid == "duplicate":
        second["id"] = first["id"]
    elif invalid == "incomplete":
        second["status"] = "in_progress"
    elif invalid == "empty_content":
        second["content"] = []
    elif invalid == "bad_content":
        second["role"] = "user"
    elif invalid == "disagreement":
        final = events[-1]["response"]
        assert isinstance(final, dict)
        final["output"] = [first, dict(second, content=[{"type": "output_text", "text": "Changed", "annotations": []}])]
    elif invalid == "partial":
        events = events[:-2]
    body = EventStream(events)
    retained: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises((ValueError, RuntimeError)):
                    await OpenAIAgenticGenerator("model", client).generate(
                        AgenticGenerationRequest((), "Instructions", (), retained.append))
        assert body.closed
        assert retained[0]["phase"] == "commentary"
        assert retained[0]["content"][0]["text"] == "Retained."
        assert len(retained) == (2 if invalid == "disagreement" else 1)
    asyncio.run(run())


@pytest.mark.parametrize("duplicate", ["item_id", "call_id"])
def test_duplicate_function_identity_preserves_first_call_without_execution(duplicate: str) -> None:
    first = function_call()
    second = dict(first, id="fc_2", call_id="call_2")
    second["id" if duplicate == "item_id" else "call_id"] = first["id" if duplicate == "item_id" else "call_id"]
    body = EventStream(response_events([first, second]))
    retained: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises(ValueError):
                    await OpenAIAgenticGenerator("model", client).generate(
                        AgenticGenerationRequest((), "Instructions", (), retained.append))
        assert body.closed and len(retained) == 1
        assert retained[0]["call_id"] == "call_1"
    asyncio.run(run())


@pytest.mark.parametrize("status", ["absent", None, "completed", "in_progress", "incomplete"])
def test_reasoning_completion_allows_optional_status_and_preserves_context(status: str | None) -> None:
    reasoning: dict[str, object] = {"type": "reasoning", "id": "rs_context", "summary": [], "encrypted_content": "opaque"}
    if status != "absent":
        reasoning["status"] = status
    body = EventStream(response_events([reasoning, message("Done")]))
    retained: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                generator = OpenAIAgenticGenerator("model", client)
                request = AgenticGenerationRequest((), "Instructions", (), retained.append)
                if status in ("in_progress", "incomplete"):
                    with pytest.raises(ValueError):
                        await generator.generate(request)
                    assert retained == []
                else:
                    result = await generator.generate(request)
                    assert result.output_items[0] == retained[0] == {"type": "reasoning", "id": "rs_context",
                        "summary": [], "encrypted_content": "opaque"}
        assert body.closed
    asyncio.run(run())


@pytest.mark.parametrize("phase", [None, "commentary", "final_answer"])
@pytest.mark.parametrize("text", [" ", "x" * 16001])
def test_invalid_assistant_message_fails_before_output_callback(phase: str | None, text: str) -> None:
    invalid = message(text)
    invalid["phase"] = phase
    invalid["id"] = "invalid"
    prior = message("Valid prior item", "commentary")
    body = EventStream(response_events([prior, invalid]))
    retained: list[dict[str, object]] = []

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body))) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                with pytest.raises(ValueError, match="assistant message"):
                    await OpenAIAgenticGenerator("model", client).generate(
                        AgenticGenerationRequest((), "Instructions", (), retained.append))
        assert body.closed
        assert len(retained) == 1
        assert retained[0]["id"] == prior["id"]

    asyncio.run(run())
