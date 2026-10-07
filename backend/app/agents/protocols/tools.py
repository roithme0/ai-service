"""Interface for agent tool discovery and instructions."""

from typing import Protocol, TypeVar

from app.agents.models.tools import RegisteredTool

ArtifactT = TypeVar("ArtifactT", covariant=True)


class ToolSource(Protocol[ArtifactT]):
    def registered_tools(self) -> tuple[RegisteredTool[ArtifactT], ...]: ...

    @property
    def instructions(self) -> str: ...
