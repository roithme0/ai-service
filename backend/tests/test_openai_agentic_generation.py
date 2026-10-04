import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest

import httpx
from openai import AsyncOpenAI

from app.models.openai_agentic_generation import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OpenAIAgenticGenerator,
)
from typing import Never

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse
from app.sessions.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.history import CallRecord, ToolResultRecord, model_input
from app.sessions.conversation import ConversationSessionSettings, ConversationSessionStore
from app.sessions.model_turns import ModelTurnStrategy
from app.sessions.tool_turns import run_tool_turn
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation
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
    responses: list[AgenticGenerationResponse] = []
    recorder = ToolTurnRecorder[Never]()

    def record_response(response: AgenticGenerationResponse, accepted: bool | None) -> tuple[CallRecord, ...]:
        responses.append(response)
        return recorder.record_response(response, accepted)

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
                    }, execute),)),), 6, 3, 8, record_response=record_response,
                    start_execution=recorder.start_execution, record_result=recorder.record_result,
                )
                assert result.kind == "completed"
                assert result.text == "That call failed."

    asyncio.run(run())
    assert not invoked
    assert responses[-1].output_items[0]["phase"] == "final_answer"
    assert len(requests) == 2
    assert all(request["stream"] is True for request in requests)
    assert all(request["store"] is False and request["parallel_tool_calls"] is False for request in requests)
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


def test_fragmented_messages_preserve_order_and_phases() -> None:
    output = [message("Checking.", "commentary"), message("Finished.")]
    body = EventStream(response_events(output))

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=body)
        )) as http_client:
            async with AsyncOpenAI(api_key="test", http_client=http_client, max_retries=0) as client:
                result = await OpenAIAgenticGenerator("gpt-5.6-sol", client).generate(
                    AgenticGenerationRequest((), "Instructions", ()))
                assert result.text == "Checking.Finished."
                assert [item["phase"] for item in result.output_items] == ["commentary", "final_answer"]
                assert [item["id"] for item in result.output_items] == [item["id"] for item in output]
                assert result.tool_calls == ()
        assert body.closed

    asyncio.run(run())


@pytest.mark.parametrize("ending", ["response.failed", "response.incomplete", "error", "missing", "disconnect"])
@pytest.mark.parametrize("prior_success", [False, True])
def test_failed_stream_never_records_partial_calls_or_executes_tools(ending: str, prior_success: bool) -> None:
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
                session_id = store.create("Context", ConversationSessionSettings(20)).session_id
                store.append_user_message(session_id, "Run")
                strategy = ModelTurnStrategy(store, OpenAIAgenticGenerator("gpt-5.6-sol", client),
                    lambda context: context, (LocalToolSource((RegisteredTool("sample",
                    {"type": "function", "name": "sample"}, execute),)),))
                assert (await strategy(session_id)).kind == "generation_failed"
                history = store.history(session_id)
                assert len([record for record in history if isinstance(record, CallRecord)]) == int(prior_success)
                results = [record for record in history if isinstance(record, ToolResultRecord)]
                assert len(results) == int(prior_success)
                replay = model_input(history)
                if prior_success:
                    assert any(item.get("output") == results[0].output for item in replay)
                    assert store.read(session_id).snapshot.artifacts[0].payload == "retained payload"
                else:
                    assert replay == ({"role": "user", "content": "Run"},)
                assert (await strategy(session_id)).kind == "generation_failed"
        assert len(bodies) == 1 + int(prior_success)
        assert len(invocations) == int(prior_success)
        assert all(body.closed for body in bodies)

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_deadline_and_cancellation_close_stream_without_restart(monkeypatch: pytest.MonkeyPatch, cancel: bool) -> None:
    monkeypatch.setattr("app.models.openai_agentic_generation.OPENAI_REQUEST_TIMEOUT_SECONDS", 0.05)
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
    monkeypatch.setattr("app.models.openai_agentic_generation.OPENAI_REQUEST_TIMEOUT_SECONDS", 0.01)
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
