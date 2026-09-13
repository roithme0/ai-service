"""OpenAI implementation of the provider-neutral text generator."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.models.text_generation import TextGenerationRequest, TextGenerationResponse


OPENAI_REQUEST_TIMEOUT_SECONDS = 60.0
OPENAI_MAX_OUTPUT_TOKENS = 4_096
logger = logging.getLogger(__name__)


class OpenAITextGenerator:
    def __init__(self, model: str, client: AsyncOpenAI) -> None:
        self._model = model
        self._client = client

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        response = await self._client.responses.create(
            model=self._model,
            input=[{"role": message.role, "content": message.text} for message in request.messages],
            max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            store=False,
            timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        )
        if response.error is not None:
            logger.error(
                "OpenAI response %s failed (status=%s, code=%s)",
                response.id,
                response.status,
                response.error.code,
            )
            raise ValueError("OpenAI response contained an error")
        if response.status != "completed":
            raise ValueError("OpenAI response did not complete")
        return TextGenerationResponse(text=response.output_text)
