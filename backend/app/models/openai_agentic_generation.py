"""OpenAI Responses adapter for the provider-neutral agentic loop."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import cast

from openai import AsyncOpenAI

from app.models.agentic_generation import (
    AgenticGenerationRequest,
    AgenticGenerationResponse,
    AgenticToolCall,
)


from app.models.output_items import final_response_text, validate_message_item


OPENAI_REQUEST_TIMEOUT_SECONDS = 120.0
OPENAI_MAX_OUTPUT_TOKENS = 16_384


class OpenAIAgenticGenerator:
    def __init__(self, model: str, client: AsyncOpenAI) -> None:
        self._model = model
        self._client = client

    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
        output_items: list[dict[str, object]] = []
        completed = False
        async with asyncio.timeout(OPENAI_REQUEST_TIMEOUT_SECONDS):
            async with self._client.responses.stream(
                model=self._model,
                input=list(request.input_items),
                instructions=request.instructions,
                tools=list(request.tools),
                include=["reasoning.encrypted_content"],
                parallel_tool_calls=False,
                max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
                store=False,
                timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
            ) as stream:
                async for event in stream:
                    if completed:
                        raise ValueError("OpenAI stream continued after completion")
                    if event.type in ("error", "response.failed", "response.incomplete"):
                        raise ValueError("OpenAI response stream failed")
                    if event.type == "response.output_item.done":
                        if event.output_index != len(output_items):
                            raise ValueError("OpenAI output item completion out of order")
                        item = _completed_item(event.item.model_dump(mode="json"))
                        identity = item["id"]
                        if not isinstance(identity, str) or any(previous["id"] == identity for previous in output_items):
                            raise ValueError("OpenAI duplicate output item")
                        if item["type"] == "function_call":
                            call_id = cast(str, item["call_id"])
                            if any(previous.get("call_id") == call_id for previous in output_items
                                   if previous["type"] == "function_call"):
                                raise ValueError("OpenAI duplicate function call identity")
                        output_items.append(item)
                        if request.on_output_item is not None:
                            request.on_output_item(deepcopy(item))
                    elif event.type == "response.completed":
                        if event.response.status != "completed" or event.response.error is not None:
                            raise ValueError("OpenAI response did not complete successfully")
                        final_items = [_completed_item(item.model_dump(mode="json")) for item in event.response.output]
                        if final_items != output_items:
                            raise ValueError("OpenAI completed response disagrees with recorded items")
                        completed = True
                if not completed:
                    raise ValueError("OpenAI response did not complete")
        calls = tuple(AgenticToolCall(str(item["call_id"]), str(item["name"]), str(item["arguments"]))
                      for item in output_items if item["type"] == "function_call")
        response = AgenticGenerationResponse(tuple(output_items), calls, None)
        return AgenticGenerationResponse(response.output_items, calls, final_response_text(response))


def _completed_item(item: dict[str, object]) -> dict[str, object]:
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise ValueError("OpenAI output item lacks identity")
    if item.get("status") != "completed" and not (item.get("type") == "reasoning" and item.get("status") is None):
        raise ValueError("OpenAI output item is incomplete")
    item_type = item.get("type")
    if item_type == "reasoning":
        if not isinstance(item.get("summary"), list):
            raise ValueError("OpenAI reasoning summary is invalid")
        return _replay_item(item, ("type", "id", "summary", "encrypted_content"))
    if item_type == "function_call":
        if any(not isinstance(item.get(key), str) or not item[key] for key in ("call_id", "name", "arguments")):
            raise ValueError("OpenAI function call is invalid")
        return _replay_item(item, ("type", "id", "call_id", "name", "arguments"))
    if item_type == "message":
        content = item.get("content")
        if item.get("role") != "assistant" or not isinstance(content, list) or not content:
            raise ValueError("OpenAI message is invalid")
        for part in cast(list[object], content):
            if not isinstance(part, dict) or part.get("type") not in ("output_text", "refusal"):
                raise ValueError("OpenAI message content is invalid")
            part = cast(dict[str, object], part)
            part.pop("parsed", None)
            key = "text" if part["type"] == "output_text" else "refusal"
            if not isinstance(part.get(key), str):
                raise ValueError("OpenAI message content is incomplete")
        if item.get("phase") not in (None, "commentary", "final_answer"):
            raise ValueError("OpenAI message phase is invalid")
        replay = _replay_item(item, ("type", "id", "role", "content", "phase"))
        if replay.get("phase") is None:
            replay.pop("phase", None)
        validate_message_item(replay)
        return replay
    raise ValueError("OpenAI response contained an unsupported output item")


def _replay_item(item: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {field: item[field] for field in fields if field in item}
