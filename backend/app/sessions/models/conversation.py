"""Conversation settings, snapshots, and lifecycle outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from app.sessions.models.artifacts import PublishedArtifact
from app.sessions.models.session import SessionSnapshot
from app.sessions.models.timeline import TimelineItem
from app.sessions.models.turns import ActiveTurnStatus, TurnKind

ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ConversationSessionSettings:
    max_artifacts: int

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError("max_artifacts must be positive")


@dataclass(frozen=True)
class ConversationTurnResult(Generic[ArtifactT]):
    kind: TurnKind
    turn_id: str
    text: str | None
    artifacts: tuple[PublishedArtifact[ArtifactT], ...]


@dataclass(frozen=True)
class ConversationTurnReservation(Generic[ContextT, ArtifactT]):
    turn_id: str
    snapshot: SessionSnapshot[ContextT]
    previous_artifacts: tuple[PublishedArtifact[ArtifactT], ...]


@dataclass(frozen=True)
class ConversationSnapshot(Generic[ContextT, ArtifactT]):
    session: SessionSnapshot[ContextT]
    artifacts: tuple[PublishedArtifact[ArtifactT], ...]
    terminal_turn_id: str | None
    terminal_turn_kind: TurnKind | None
    timeline: tuple[TimelineItem, ...]
    active_turn_id: str | None
    active_turn_status: ActiveTurnStatus | None
    sequence: int


@dataclass(frozen=True)
class ConversationReadActive(Generic[ContextT, ArtifactT]):
    snapshot: ConversationSnapshot[ContextT, ArtifactT]
    kind: Literal["active"] = "active"
