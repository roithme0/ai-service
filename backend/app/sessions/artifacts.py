"""Validated artifact candidates and retained envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ArtifactCandidate(Generic[ArtifactT]):
    type: str
    payload: ArtifactT


@dataclass(frozen=True)
class ArtifactEnvelope(Generic[ArtifactT]):
    artifact_id: str
    type: str
    created_at: datetime
    turn_id: str
    payload: ArtifactT


@dataclass(frozen=True)
class PublishedArtifact(ArtifactEnvelope[ArtifactT]):
    order: int


@dataclass(frozen=True)
class ArtifactToolOutput:
    kind: str
