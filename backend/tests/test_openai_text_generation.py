import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.models.openai_text_generation import (
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REQUEST_TIMEOUT_SECONDS,
    OpenAITextGenerator,
)
from app.models.text_generation import TextGenerationRequest, TextGenerationResponse, generate_text
from app.sessions.text_sessions import TextMessage


def test_openai_generator_sends_conversation_without_provider_storage() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload: object = json.loads(request.content)
        assert isinstance(payload, dict)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.6-sol",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "A useful answer", "annotations": []}
                        ],
                    }
                ],
            },
        )

    async def run() -> TextGenerationResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test-key", http_client=http_client) as client:
                generator = OpenAITextGenerator("gpt-5.6-sol", client)
                return await generate_text(
                    generator,
                    TextGenerationRequest(
                        (TextMessage("user", "First"), TextMessage("assistant", "Second"), TextMessage("user", "Third"))
                    ),
                )

    assert asyncio.run(run()) == TextGenerationResponse("A useful answer")
    assert len(requests) == 1
    assert requests[0]["model"] == "gpt-5.6-sol"
    assert requests[0]["input"] == [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Second"},
        {"role": "user", "content": "Third"},
    ]
    assert requests[0]["store"] is False
    assert requests[0]["max_output_tokens"] == OPENAI_MAX_OUTPUT_TOKENS
    assert OPENAI_REQUEST_TIMEOUT_SECONDS > 0
    assert "instructions" not in requests[0]
    assert "tools" not in requests[0]


def test_openai_generator_rejects_incomplete_response() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.6-sol",
                "status": "incomplete",
                "output": [],
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test-key", http_client=http_client) as client:
                generator = OpenAITextGenerator("gpt-5.6-sol", client)
                await generator.generate(TextGenerationRequest((TextMessage("user", "Hello"),)))

    with pytest.raises(ValueError, match="did not complete"):
        asyncio.run(run())


def test_openai_generator_logs_response_error_without_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_failed",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.6-sol",
                "status": "failed",
                "error": {
                    "code": "server_error",
                    "message": "Sensitive provider detail",
                },
                "output": [],
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            async with AsyncOpenAI(api_key="test-key", http_client=http_client) as client:
                generator = OpenAITextGenerator("gpt-5.6-sol", client)
                await generator.generate(TextGenerationRequest((TextMessage("user", "Hello"),)))

    with pytest.raises(ValueError, match="contained an error"):
        asyncio.run(run())

    assert "resp_failed" in caplog.text
    assert "server_error" in caplog.text
    assert "Sensitive provider detail" not in caplog.text
