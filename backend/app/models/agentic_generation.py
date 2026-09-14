"""Provider-neutral bounded tool-call generation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias


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
