"""Shared turn lifecycle types."""

from dataclasses import dataclass
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import Field

from app.sessions.models.timeline import TimelineItem

ArtifactT = TypeVar("ArtifactT")


TurnExecutionKind = Literal["completed", "generation_failed"]
TerminalTurnKind = Literal[TurnExecutionKind, "conflict"]
TurnKind = Literal[TurnExecutionKind, "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]
ActiveTurnStatus = Literal["in_progress", "closing"]
TurnSnapshotStatus = Literal["pending", ActiveTurnStatus, TerminalTurnKind]


@dataclass(frozen=True)
class TurnSnapshot(Generic[ArtifactT]):
    turn_id: str
    user_message_id: str
    status: TurnSnapshotStatus
    timeline: tuple[Annotated[TimelineItem[ArtifactT], Field(discriminator="kind")], ...]
