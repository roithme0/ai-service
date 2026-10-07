"""Caller-provided context contracts and retained session context."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.sessions.models.presentation import ArtifactCapability


@dataclass(frozen=True)
class ContextIssue:
    location: tuple[str | int, ...]
    message: str


@dataclass(frozen=True)
class SessionContext:
    model_context: str
    artifact_capabilities: tuple[ArtifactCapability, ...] = ()


class ContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    context: dict[str, JsonValue]
    artifact_capabilities: list[ArtifactCapability] = Field(default_factory=list, alias="artifactCapabilities", max_length=20)

    @field_validator("artifact_capabilities")
    @classmethod
    def unique_types(cls, capabilities: list[ArtifactCapability]) -> list[ArtifactCapability]:
        if len({item.type for item in capabilities}) != len(capabilities):
            raise ValueError("artifact capability types must be unique")
        return capabilities

