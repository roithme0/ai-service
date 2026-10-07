"""Provider-independent agent tool registration and invocation."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.sessions.models.execution import ToolExecution

ArtifactT = TypeVar("ArtifactT", covariant=True)


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
        self._handlers = handlers
        self.schemas = tuple(tool.schema for tool in tools)

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    async def invoke(self, name: str, arguments: str) -> ToolExecution[ArtifactT]:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "unknown_tool"}), failed=True)
        execution = handler(ToolInvocation(name, arguments))
        return await execution if inspect.isawaitable(execution) else execution
