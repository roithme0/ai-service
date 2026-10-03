import asyncio
import json

import httpx
from openai import AsyncOpenAI

from app.models.openai_agentic_generation import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OpenAIAgenticGenerator,
)
from typing import Never

from app.models.agentic_generation import AgenticGenerationResponse
from app.sessions.history import CallRecord
from app.sessions.tool_turns import run_tool_turn
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation
from tool_turn_recorder import ToolTurnRecorder


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
        return httpx.Response(200, json={"id": f"resp_{len(requests)}", "object": "response",
                                          "created_at": 1, "model": "gpt-5.6-sol",
                                          "status": "completed", "output": output})

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
            async with AsyncOpenAI(api_key="test-key", http_client=http_client) as client:
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
