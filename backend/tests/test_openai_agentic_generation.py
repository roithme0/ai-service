import asyncio
import json

import httpx
from openai import AsyncOpenAI

from app.models.openai_agentic_generation import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OpenAIAgenticGenerator,
)
from app.recipe_improvement.agentic_turns import generate_agentic_recipe_turn
from app.recipe_improvement.proposals import ProposalRejected, ProposalRegistrationOutcome
from app.sessions.text_sessions import TextMessage


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
                       "name": "register_recipe_proposal", "arguments": "not-json", "status": "completed"}]
        else:
            assert all("status" not in item for item in payload["input"])
            output = [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "I could not register that.",
                                    "annotations": []}]}]
        return httpx.Response(200, json={"id": f"resp_{len(requests)}", "object": "response",
                                          "created_at": 1, "model": "gpt-5.6-sol",
                                          "status": "completed", "output": output})

    invoked = False

    def register(base: object, candidate: object) -> ProposalRegistrationOutcome:
        nonlocal invoked
        invoked = True
        return ProposalRejected(reason="invalid_candidate")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test-key", http_client=http_client) as client:
                result = await generate_agentic_recipe_turn(
                    OpenAIAgenticGenerator("gpt-5.6-sol", client),
                    (TextMessage("user", "Improve it"),), "Recipe context", "Instructions", register,
                )
                assert result.kind == "completed"
                assert result.text == "I could not register that."

    asyncio.run(run())
    assert not invoked
    assert len(requests) == 2
    assert all(request["store"] is False and request["parallel_tool_calls"] is False for request in requests)
    assert all(request["max_output_tokens"] == OPENAI_MAX_OUTPUT_TOKENS for request in requests)
    assert all(request["include"] == ["reasoning.encrypted_content"] for request in requests)
    assert requests[0]["input"] == [
        {"role": "user", "content": "Recipe context"},
        {"role": "user", "content": "Improve it"},
    ]
    replay = requests[1]["input"]
    assert isinstance(replay, list)
    assert replay[2] == {"id": "rs_1", "type": "reasoning", "summary": [],
                         "encrypted_content": "opaque-reasoning"}
    assert replay[3] == {"id": "fc_1", "type": "function_call", "call_id": "call_1",
                         "name": "register_recipe_proposal", "arguments": "not-json"}
    assert replay[4]["type"] == "function_call_output"
    assert replay[4]["call_id"] == "call_1"
    assert json.loads(replay[4]["output"]) == {"kind": "rejected", "reason": "invalid_arguments"}
