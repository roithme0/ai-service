"""Retained session context."""

from __future__ import annotations

from dataclasses import dataclass

from app.sessions.models.artifacts import ArtifactCapability


@dataclass(frozen=True)
class SessionContext:
    model_context: str
    artifact_capabilities: tuple[ArtifactCapability, ...] = ()
