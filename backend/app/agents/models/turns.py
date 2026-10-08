from dataclasses import dataclass
from typing import Generic, TypeVar

from app.sessions.models.turns import TurnExecutionKind


ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ToolTurnResult(Generic[ArtifactT]):
    kind: TurnExecutionKind
    text: str | None
    artifacts: tuple[ArtifactT, ...]
