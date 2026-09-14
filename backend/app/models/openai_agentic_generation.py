"""OpenAI Responses adapter for the provider-neutral agentic loop."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.models.agentic_generation import (
    AgenticGenerationRequest,
    AgenticGenerationResponse,
    AgenticToolCall,
)
from app.models.openai_text_generation import OPENAI_MAX_OUTPUT_TOKENS, OPENAI_REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class OpenAIAgenticGenerator:
    def __init__(self, model: str, client: AsyncOpenAI) -> None:
        self._model = model
        self._client = client

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        response = await self._client.responses.create(
            model=self._model,
            input=list(request.input_items),
            instructions=request.instructions,
            tools=list(request.tools),
            include=["reasoning.encrypted_content"],
            parallel_tool_calls=False,
            max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
            store=False,
            timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        )
        if response.error is not None:
            logger.error("OpenAI response %s failed (status=%s, code=%s)", response.id, response.status, response.error.code)
            raise ValueError("OpenAI response contained an error")
        if response.status != "completed":
            raise ValueError("OpenAI response did not complete")
        output_items: list[dict[str, object]] = []
        calls: list[AgenticToolCall] = []
        for item in response.output:
            dumped = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            if not isinstance(dumped, dict):
                raise ValueError("OpenAI response contained an unsupported output item")
            output_items.append(dumped)
            if dumped.get("type") == "function_call":
                call_id = dumped.get("call_id")
                name = dumped.get("name")
                arguments = dumped.get("arguments")
                if (not isinstance(call_id, str) or not call_id
                    or not isinstance(name, str) or not name
                    or not isinstance(arguments, str) or not arguments):
                    raise ValueError("OpenAI response contained an invalid function call")
                calls.append(AgenticToolCall(call_id=call_id, name=name, arguments=arguments))
        text = response.output_text if isinstance(response.output_text, str) and response.output_text.strip() else None
        return AgenticGenerationResponse(tuple(output_items), tuple(calls), text)
