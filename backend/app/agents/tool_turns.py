"""Bounded provider-neutral tool-call orchestration for one assistant turn."""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import TypeVar

from app.agents.protocols.generation import AgenticGenerator
from app.agents.models.generation import AgenticGenerationRequest, AgenticInputItem, AgenticToolCall
from app.agents.generation_messages import final_response_text, validate_message_item
from app.sessions.models.history import CallRecord, HistoryRecord
from app.agents.protocols.tools import ToolSource
from app.agents.models.tools import RegisteredTool
from app.agents.tool_registry import ToolRegistry
from app.sessions.models.execution import ToolExecution
from app.agents.models.turns import ToolTurnResult
from app.sessions.web_search import WebSearchConfig


ArtifactT = TypeVar("ArtifactT")


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
    record_item: Callable[[AgenticInputItem], HistoryRecord],
    start_execution: Callable[[CallRecord], None],
    record_result: Callable[[CallRecord, ToolExecution[ArtifactT]], ToolExecution[ArtifactT]],
    web_search: WebSearchConfig | None = None,
) -> ToolTurnResult[ArtifactT]:
    combined_tools, instructions = combine_tool_inputs(tool_sources, instructions)
    registry = ToolRegistry(combined_tools)

    input_items: list[AgenticInputItem] = [{"role": "user", "content": context}]
    input_items.extend(retained_input)
    artifacts: list[ArtifactT] = []
    attempts = 0
    search_calls = 0
    for _ in range(max_provider_responses):
        search_allowance = web_search.max_calls_per_turn - search_calls if web_search is not None else 0
        recorded_items: list[AgenticInputItem] = []
        records: list[HistoryRecord] = []

        def receive_item(item: AgenticInputItem) -> None:
            nonlocal search_calls
            validate_message_item(item)
            if item.get("type") == "web_search_call":
                if web_search is None or search_allowance <= 0 or search_calls >= web_search.max_calls_per_turn:
                    raise ValueError("provider exceeded advertised web search allowance")
                search_calls += 1
            recorded_items.append(deepcopy(item))
            records.append(record_item(item))

        response = await generator.generate(AgenticGenerationRequest(
            input_items=tuple(input_items), instructions=instructions,
            tools=registry.schemas + (({"type": "web_search"},) if search_allowance > 0 else ()),
            on_output_item=receive_item,
            max_hosted_tool_calls=search_allowance if search_allowance > 0 else None,
        ))
        provider_calls = tuple(AgenticToolCall(str(item.get("call_id")), str(item.get("name")), str(item.get("arguments")))
                               for item in response.output_items if item.get("type") == "function_call")
        if provider_calls != response.tool_calls:
            raise ValueError("provider output and requested calls must match in order")
        if recorded_items and tuple(recorded_items) != response.output_items:
            raise ValueError("completed response disagrees with recorded output")
        if not recorded_items:
            for item in response.output_items:
                receive_item(item)

        text = final_response_text(response)
        recorded_calls = tuple(record for record in records if isinstance(record, CallRecord))
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
        if text is not None:
            return ToolTurnResult("completed", text, tuple(artifacts))
    return ToolTurnResult("generation_failed", None, tuple(artifacts))
