"""Tool execution outcomes recorded by sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.sessions.models.artifacts import ArtifactToolOutput

ArtifactT = TypeVar("ArtifactT", covariant=True)


@dataclass(frozen=True)
class ToolExecution(Generic[ArtifactT]):
    output: str | ArtifactToolOutput
    artifact: ArtifactT | None = None
    failed: bool = False
