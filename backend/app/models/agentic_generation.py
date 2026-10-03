"""Provider-neutral bounded tool-call generation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias


@dataclass(frozen=True)
class AgenticToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AgenticToolResult:
    call_id: str
    output: str


AgenticInputItem: TypeAlias = dict[str, object]
AgenticOutputItem: TypeAlias = dict[str, object]
AssistantMessagePhase: TypeAlias = Literal["commentary", "final_answer"]


def message_phase(item: AgenticInputItem) -> AssistantMessagePhase | None:
    phase = item.get("phase")
    if phase == "commentary":
        return "commentary"
    if phase == "final_answer":
        return "final_answer"
    return None


@dataclass(frozen=True)
class AgenticGenerationRequest:
    input_items: tuple[AgenticInputItem, ...]
    instructions: str
    tools: tuple[AgenticInputItem, ...]


@dataclass(frozen=True)
class AgenticGenerationResponse:
    output_items: tuple[AgenticOutputItem, ...]
    tool_calls: tuple[AgenticToolCall, ...]
    text: str | None


class AgenticGenerator(Protocol):
    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse: ...
