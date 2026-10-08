"""Contracts for agent tool invocation, registration, and discovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.sessions.models.execution import ToolExecution

ArtifactT = TypeVar("ArtifactT", covariant=True)


@dataclass(frozen=True)
class ToolInvocation:
    name: str
    arguments: str


@dataclass(frozen=True)
class RegisteredTool(Generic[ArtifactT]):
    name: str
    schema: dict[str, object]
    execute: Callable[
        [ToolInvocation], ToolExecution[ArtifactT] | Awaitable[ToolExecution[ArtifactT]]
    ]


@dataclass(frozen=True)
class LocalToolSource(Generic[ArtifactT]):
    tools: tuple[RegisteredTool[ArtifactT], ...]
    instructions: str = ""

    def registered_tools(self) -> tuple[RegisteredTool[ArtifactT], ...]:
        return self.tools
