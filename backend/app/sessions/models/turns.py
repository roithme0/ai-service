"""Shared turn lifecycle types."""

from dataclasses import dataclass
from typing import Literal


TurnExecutionKind = Literal["completed", "generation_failed"]
TerminalTurnKind = Literal[TurnExecutionKind, "conflict"]
TurnKind = Literal[TurnExecutionKind, "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]
ActiveTurnStatus = Literal["in_progress", "closing"]
TurnSnapshotStatus = Literal["pending", ActiveTurnStatus, TerminalTurnKind]


@dataclass(frozen=True)
class TurnSnapshot:
    turn_id: str
    user_message_id: str
    status: TurnSnapshotStatus
