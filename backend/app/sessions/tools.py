"""Provider-independent registration and invocation of session tools."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolExecution(Generic[ArtifactT]):
    output: str
    artifact: ArtifactT | None = None


@dataclass(frozen=True)
class RegisteredTool(Generic[ArtifactT]):
    name: str
    schema: dict[str, object]
    execute: Callable[
        [ToolInvocation], ToolExecution[ArtifactT] | Awaitable[ToolExecution[ArtifactT]]
    ]


class ToolRegistry(Generic[ArtifactT]):
    def __init__(self, tools: tuple[RegisteredTool[ArtifactT], ...]) -> None:
        handlers: dict[
            str,
            Callable[[ToolInvocation], ToolExecution[ArtifactT] | Awaitable[ToolExecution[ArtifactT]]],
        ] = {}
        for tool in tools:
            if (not tool.name or tool.name in handlers or tool.schema.get("name") != tool.name
                or tool.schema.get("type") != "function"):
                raise ValueError("tools must have unique names matching their schemas")
            handlers[tool.name] = tool.execute
        if not handlers:
            raise ValueError("at least one tool is required")
        self._handlers = handlers
        self.schemas = tuple(tool.schema for tool in tools)

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    async def invoke(self, name: str, arguments: str) -> ToolExecution[ArtifactT]:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "unknown_tool"}))
        execution = handler(ToolInvocation(name, arguments))
        return await execution if inspect.isawaitable(execution) else execution
