"""Bounded provider-neutral tool-call orchestration for one assistant turn."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerator, AgenticInputItem, AgenticToolCall, AgenticGenerationResponse, message_phase
from app.sessions.history import CallRecord, final_response_text
from app.sessions.text_sessions import MAX_MESSAGE_LENGTH
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
            }), failed=True), attempts
        attempts += 1
    return await registry.invoke(call.name, call.arguments), attempts


async def run_tool_turn(
    generator: AgenticGenerator,
    retained_input: tuple[AgenticInputItem, ...],
    context: str,
    instructions: str,
    tool_sources: tuple[ToolSource[ArtifactT], ...],
    max_attempts: int,
    max_successes: int | None,
    max_provider_responses: int,
    *,
    record_response: Callable[[AgenticGenerationResponse, bool | None], tuple[CallRecord, ...]],
    start_execution: Callable[[CallRecord], None],
    record_result: Callable[[CallRecord, ToolExecution[ArtifactT]], ToolExecution[ArtifactT]],
) -> ToolTurnResult[ArtifactT]:
    combined_tools, instructions = combine_tool_inputs(tool_sources, instructions)
    registry = ToolRegistry(combined_tools)

    input_items: list[AgenticInputItem] = [{"role": "user", "content": context}]
    input_items.extend(retained_input)
    artifacts: list[ArtifactT] = []
    attempts = 0
    for _ in range(max_provider_responses):
        response = await generator.generate(AgenticGenerationRequest(
            input_items=tuple(input_items), instructions=instructions,
            tools=registry.schemas,
        ))
        if not response.tool_calls:
            text = final_response_text(response)
            messages = [item for item in response.output_items if item.get("type") == "message"]
            if text is None and messages and all(message_phase(item) == "commentary" for item in messages):
                record_response(response, None)
                input_items.extend(response.output_items)
                continue
            valid_text = text is not None and bool(text.strip()) and len(text) <= MAX_MESSAGE_LENGTH
            record_response(response, valid_text)
            if not valid_text:
                return ToolTurnResult("generation_failed", None, tuple(artifacts))
            return ToolTurnResult("completed", text, tuple(artifacts))
        recorded_calls = record_response(response, None)
        if tuple(record.call for record in recorded_calls) != response.tool_calls:
            raise ValueError("recorded calls must match requested calls in order")

        input_items.extend(response.output_items)
        for index, call in enumerate(response.tool_calls):
            recorded = recorded_calls[index]
            if (registry.has_tool(call.name)
                and attempts < max_attempts and (max_successes is None or len(artifacts) < max_successes)):
                start_execution(recorded)
            execution, attempts = await execute_tool_call(
                registry, call, attempts, len(artifacts), max_attempts, max_successes,
            )
            execution = record_result(recorded, execution)
            if execution.artifact is not None:
                artifacts.append(execution.artifact)
            if not isinstance(execution.output, str):
                raise ValueError("artifact tool outcome must be accepted before model continuation")
            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": execution.output})
    return ToolTurnResult("generation_failed", None, tuple(artifacts))
