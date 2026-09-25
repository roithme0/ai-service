"""Bounded provider-neutral tool-call orchestration for one assistant turn."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerator, AgenticInputItem
from app.sessions.text_sessions import MAX_MESSAGE_LENGTH, TextMessage
from app.sessions.tools import RegisteredTool, ToolExecution, ToolRegistry


ArtifactT = TypeVar("ArtifactT")


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
    registry = ToolRegistry(tools)

    input_items: list[AgenticInputItem] = [{"role": "user", "content": context}]
    input_items.extend({"role": message.role, "content": message.text} for message in messages)
    artifacts: list[ArtifactT] = []
    attempts = 0
    for _ in range(max_provider_responses):
        response = await generator.generate(AgenticGenerationRequest(
            input_items=tuple(input_items), instructions=instructions,
            tools=registry.schemas,
        ))
        if not response.tool_calls:
            if response.text is None or not response.text.strip() or len(response.text) > MAX_MESSAGE_LENGTH:
                return ToolTurnResult("generation_failed", None, tuple(artifacts))
            return ToolTurnResult("completed", response.text, tuple(artifacts))

        input_items.extend(response.output_items)
        for call in response.tool_calls:
            if registry.has_tool(call.name) and (attempts >= max_attempts or len(artifacts) >= max_successes):
                execution = ToolExecution[ArtifactT](json.dumps({
                    "kind": "limit_reached", "attempts": attempts, "successes": len(artifacts),
                }))
            else:
                if registry.has_tool(call.name):
                    attempts += 1
                execution = await registry.invoke(call.name, call.arguments)
                if execution.artifact is not None:
                    artifacts.append(execution.artifact)
            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": execution.output})
    return ToolTurnResult("generation_failed", None, tuple(artifacts))
