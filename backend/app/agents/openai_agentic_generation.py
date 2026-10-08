"""OpenAI Responses adapter for the provider-neutral agentic loop."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import cast

from openai import AsyncOpenAI, omit
from openai.types.responses import ResponseCompletedEvent, ResponseOutputItemDoneEvent
from openai.types.shared import ReasoningEffort

from app.agents import config
from app.agents.models.generation import (
    AgenticGenerationRequest,
    AgenticGenerationResponse,
    AgenticToolCall,
)


from app.agents.generation_messages import final_response_text, validate_message_item

OPENAI_REQUEST_TIMEOUT_SECONDS = 120.0
OPENAI_MAX_OUTPUT_TOKENS = 16_384


class OpenAIAgenticGenerator:
    def __init__(
        self,
        model: str,
        client: AsyncOpenAI,
        *,
        reasoning_effort: ReasoningEffort = None,
    ) -> None:
        self._model = model
        self._client = client
        self._reasoning_effort = reasoning_effort

    async def generate(
        self, request: AgenticGenerationRequest
    ) -> AgenticGenerationResponse:
        output_items: list[dict[str, object]] = []
        completed = False
        async with asyncio.timeout(OPENAI_REQUEST_TIMEOUT_SECONDS):
            async with self._client.responses.stream(
                model=self._model,
                reasoning=(
                    {"effort": self._reasoning_effort}
                    if self._reasoning_effort is not None
                    else omit
                ),
                input=list(request.input_items),
                instructions=request.instructions,
                tools=list(request.tools),
                include=["reasoning.encrypted_content"],
                parallel_tool_calls=config.ALLOW_MULTIPLE_TOOL_CALLS,
                max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
                max_tool_calls=(
                    request.max_hosted_tool_calls
                    if request.max_hosted_tool_calls is not None
                    else omit
                ),
                store=False,
                timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
            ) as stream:
                async for event in stream:
                    if completed:
                        raise ValueError("OpenAI stream continued after completion")
                    if event.type in (
                        "error",
                        "response.failed",
                        "response.incomplete",
                    ):
                        raise ValueError("OpenAI response stream failed")
                    if event.type == "response.output_item.done":
                        _record_completed_item(event, output_items, request)
                    elif event.type == "response.completed":
                        _validate_completed_response(event, output_items)
                        completed = True
                if not completed:
                    raise ValueError("OpenAI response did not complete")
        calls = tuple(
            AgenticToolCall(
                str(item["call_id"]), str(item["name"]), str(item["arguments"])
            )
            for item in output_items
            if item["type"] == "function_call"
        )
        response = AgenticGenerationResponse(tuple(output_items), calls, None)
        return AgenticGenerationResponse(
            response.output_items, calls, final_response_text(response)
        )


def _record_completed_item(
    event: ResponseOutputItemDoneEvent,
    output_items: list[dict[str, object]],
    request: AgenticGenerationRequest,
) -> None:
    if event.output_index != len(output_items):
        raise ValueError("OpenAI output item completion out of order")
    item = _completed_item(event.item.model_dump(mode="json"))
    identity = item["id"]
    if not isinstance(identity, str) or any(
        previous["id"] == identity for previous in output_items
    ):
        raise ValueError("OpenAI duplicate output item")
    if item["type"] == "function_call":
        call_id = cast(str, item["call_id"])
        if any(
            previous.get("call_id") == call_id
            for previous in output_items
            if previous["type"] == "function_call"
        ):
            raise ValueError("OpenAI duplicate function call identity")
    output_items.append(item)
    if request.on_output_item is not None:
        request.on_output_item(deepcopy(item))


def _validate_completed_response(
    event: ResponseCompletedEvent,
    output_items: list[dict[str, object]],
) -> None:
    if event.response.status != "completed" or event.response.error is not None:
        raise ValueError("OpenAI response did not complete successfully")
    final_items = [
        _completed_item(item.model_dump(mode="json")) for item in event.response.output
    ]
    if [_comparison_item(item) for item in final_items] != [
        _comparison_item(item) for item in output_items
    ]:
        raise ValueError("OpenAI completed response disagrees with recorded items")


def _comparison_item(item: dict[str, object]) -> dict[str, object]:
    # Opaque reasoning tokens can differ between item and response completion.
    if item["type"] == "reasoning":
        return {key: value for key, value in item.items() if key != "encrypted_content"}
    return item


def _completed_item(item: dict[str, object]) -> dict[str, object]:
    if not isinstance(item.get("id"), str) or not item["id"]:
        raise ValueError("OpenAI output item lacks identity")
    if item.get("type") == "web_search_call":
        return _completed_web_search_item(item)
    if item.get("status") != "completed" and not (
        item.get("type") == "reasoning" and item.get("status") is None
    ):
        raise ValueError("OpenAI output item is incomplete")
    item_type = item.get("type")
    if item_type == "reasoning":
        if not isinstance(item.get("summary"), list):
            raise ValueError("OpenAI reasoning summary is invalid")
        return _replay_item(item, ("type", "id", "summary", "encrypted_content"))
    if item_type == "function_call":
        if any(
            not isinstance(item.get(key), str) or not item[key]
            for key in ("call_id", "name", "arguments")
        ):
            raise ValueError("OpenAI function call is invalid")
        return _replay_item(item, ("type", "id", "call_id", "name", "arguments"))
    if item_type == "message":
        return _completed_message_item(item)
    raise ValueError("OpenAI response contained an unsupported output item")


def _completed_web_search_item(item: dict[str, object]) -> dict[str, object]:
    if item.get("status") not in ("completed", "failed"):
        raise ValueError("OpenAI web search item is incomplete")
    action = item.get("action")
    if not isinstance(action, dict) or action.get("type") not in (
        "search",
        "open_page",
        "find_in_page",
    ):
        raise ValueError("OpenAI web search action is invalid")
    action = cast(dict[str, object], action)
    if action["type"] == "find_in_page" and any(
        not isinstance(action.get(key), str) for key in ("url", "pattern")
    ):
        raise ValueError("OpenAI web search find action is invalid")
    item["action"] = {key: value for key, value in action.items() if value is not None}
    return _replay_item(item, ("type", "id", "status", "action"))


def _completed_message_item(item: dict[str, object]) -> dict[str, object]:
    content = item.get("content")
    if item.get("role") != "assistant" or not isinstance(content, list) or not content:
        raise ValueError("OpenAI message is invalid")
    for part in cast(list[object], content):
        if not isinstance(part, dict) or part.get("type") not in (
            "output_text",
            "refusal",
        ):
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


def _replay_item(item: dict[str, object], fields: tuple[str, ...]) -> dict[str, object]:
    return {field: item[field] for field in fields if field in item}
