"""Bounded provider-neutral tool-call orchestration for one assistant turn."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerator, AgenticInputItem, AgenticToolCall
from app.sessions.text_sessions import MAX_MESSAGE_LENGTH, TextMessage
from app.sessions.tools import RegisteredTool, ToolExecution, ToolRegistry, ToolSource


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ToolTurnResult(Generic[ArtifactT]):
    kind: Literal["completed", "generation_failed"]
    text: str | None
    artifacts: tuple[ArtifactT, ...]


def combine_tool_inputs(
    tool_sources: tuple[ToolSource[ArtifactT], ...],
    instructions: str,
) -> tuple[tuple[RegisteredTool[ArtifactT], ...], str]:
    combined_tools: tuple[RegisteredTool[ArtifactT], ...] = ()
    instruction_sections: list[str] = []
    for tool_source in tool_sources:
        additional_tools: tuple[RegisteredTool[ArtifactT], ...] = tool_source.registered_tools()
        combined_tools += additional_tools
        source_instructions = tool_source.instructions
        if source_instructions.strip():
            instruction_sections.append(source_instructions)
    if instruction_sections:
        instruction_sections.append(
            "Local agent instructions (take precedence over tool-source instructions where they conflict):\n"
            + instructions
        )
        instructions = "\n\n".join(instruction_sections)
    return combined_tools, instructions


async def execute_tool_call(
    registry: ToolRegistry[ArtifactT],
    call: AgenticToolCall,
    attempts: int,
    successes: int,
    max_attempts: int,
    max_successes: int | None,
) -> tuple[ToolExecution[ArtifactT], int]:
    if registry.has_tool(call.name):
        if attempts >= max_attempts or (max_successes is not None and successes >= max_successes):
            return ToolExecution(json.dumps({
                "kind": "limit_reached", "attempts": attempts, "successes": successes,
            })), attempts
        attempts += 1
    return await registry.invoke(call.name, call.arguments), attempts


async def run_tool_turn(
    generator: AgenticGenerator,
    messages: tuple[TextMessage, ...],
    context: str,
    instructions: str,
    tool_sources: tuple[ToolSource[ArtifactT], ...],
    max_attempts: int,
    max_successes: int | None,
    max_provider_responses: int,
) -> ToolTurnResult[ArtifactT]:
    combined_tools, instructions = combine_tool_inputs(tool_sources, instructions)
    registry = ToolRegistry(combined_tools)

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
            execution, attempts = await execute_tool_call(
                registry, call, attempts, len(artifacts), max_attempts, max_successes,
            )
            if execution.artifact is not None:
                artifacts.append(execution.artifact)
            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": execution.output})
    return ToolTurnResult("generation_failed", None, tuple(artifacts))
