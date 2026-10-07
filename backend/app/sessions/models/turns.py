"""Shared turn lifecycle types."""

from typing import Literal


TurnExecutionKind = Literal["completed", "generation_failed"]
TerminalTurnKind = Literal[TurnExecutionKind, "conflict"]
TurnKind = Literal[TurnExecutionKind, "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]
ActiveTurnStatus = Literal["in_progress", "closing"]
