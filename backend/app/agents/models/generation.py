"""Provider-neutral bounded tool-call generation contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True)
class AgenticToolCall:
    call_id: str
    name: str
    arguments: str


AgenticInputItem: TypeAlias = dict[str, object]
AgenticOutputItem: TypeAlias = dict[str, object]
AssistantMessagePhase: TypeAlias = Literal["commentary", "final_answer"]


@dataclass(frozen=True)
class AgenticGenerationRequest:
    input_items: tuple[AgenticInputItem, ...]
    instructions: str
    tools: tuple[AgenticInputItem, ...]
    on_output_item: Callable[[AgenticOutputItem], None] | None = None
    max_hosted_tool_calls: int | None = None


@dataclass(frozen=True)
class AgenticGenerationResponse:
    output_items: tuple[AgenticOutputItem, ...]
    tool_calls: tuple[AgenticToolCall, ...]
    text: str | None
