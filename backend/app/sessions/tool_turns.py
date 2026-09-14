"""Bounded provider-neutral tool-call orchestration for one assistant turn."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerator, AgenticInputItem, AgenticToolCall
from app.sessions.text_sessions import MAX_MESSAGE_LENGTH, TextMessage


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ToolExecution(Generic[ArtifactT]):
    output: str
    artifact: ArtifactT | None = None


@dataclass(frozen=True)
class RegisteredTool(Generic[ArtifactT]):
    name: str
    schema: dict[str, object]
    execute: Callable[[AgenticToolCall], ToolExecution[ArtifactT]]


@dataclass(frozen=True)
class ToolTurnResult(Generic[ArtifactT]):
    kind: Literal["completed", "generation_failed"]
    text: str | None
    artifacts: tuple[ArtifactT, ...]


async def run_tool_turn(
    generator: AgenticGenerator,
    messages: tuple[TextMessage, ...],
    context: str,
    instructions: str,
    tools: tuple[RegisteredTool[ArtifactT], ...],
    max_attempts: int,
    max_successes: int,
    max_provider_responses: int,
) -> ToolTurnResult[ArtifactT]:
    handlers: dict[str, Callable[[AgenticToolCall], ToolExecution[ArtifactT]]] = {}
    for tool in tools:
        if (not tool.name or tool.name in handlers or tool.schema.get("name") != tool.name
            or tool.schema.get("type") != "function"):
            raise ValueError("tools must have unique names matching their schemas")
        handlers[tool.name] = tool.execute
    if not handlers:
        raise ValueError("at least one tool is required")

    input_items: list[AgenticInputItem] = [{"role": "user", "content": context}]
    input_items.extend({"role": message.role, "content": message.text} for message in messages)
    artifacts: list[ArtifactT] = []
    attempts = 0
    for _ in range(max_provider_responses):
        response = await generator.generate(AgenticGenerationRequest(
            input_items=tuple(input_items), instructions=instructions,
            tools=tuple(tool.schema for tool in tools),
        ))
        if not response.tool_calls:
            if response.text is None or not response.text.strip() or len(response.text) > MAX_MESSAGE_LENGTH:
                return ToolTurnResult("generation_failed", None, tuple(artifacts))
            return ToolTurnResult("completed", response.text, tuple(artifacts))

        input_items.extend(response.output_items)
        for call in response.tool_calls:
            handler = handlers.get(call.name)
            if handler is None:
                execution = ToolExecution[ArtifactT](json.dumps({"kind": "rejected", "reason": "unknown_tool"}))
            elif attempts >= max_attempts or len(artifacts) >= max_successes:
                execution = ToolExecution[ArtifactT](json.dumps({
                    "kind": "limit_reached", "attempts": attempts, "successes": len(artifacts),
                }))
            else:
                attempts += 1
                execution = handler(call)
                if execution.artifact is not None:
                    artifacts.append(execution.artifact)
            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": execution.output})
    return ToolTurnResult("generation_failed", None, tuple(artifacts))
