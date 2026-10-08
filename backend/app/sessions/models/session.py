"""Shared message, snapshot, and session operation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, TypeVar

SessionRole = Literal["user", "assistant"]
SessionUnavailableKind = Literal["unknown", "expired"]
InvalidMessageReason = Literal["blank_text", "text_too_long"]
T = TypeVar("T")


@dataclass(frozen=True)
class SessionCreation:
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class TextMessage:
    role: SessionRole
    text: str
    turn_id: str | None = None


@dataclass(frozen=True)
class SessionSnapshot(Generic[T]):
    session_id: str
    expires_at: datetime
    revision: int
    payload: T
    messages: tuple[TextMessage, ...]


@dataclass(frozen=True)
class SessionReadActive(Generic[T]):
    session: SessionSnapshot[T]
    kind: Literal["active"] = "active"


@dataclass(frozen=True)
class SessionReadUnknown:
    session_id: str
    kind: Literal["unknown"] = "unknown"


@dataclass(frozen=True)
class SessionReadExpired:
    session_id: str
    expires_at: datetime
    kind: Literal["expired"] = "expired"


@dataclass(frozen=True)
class SessionMessageAppendAccepted:
    session_id: str
    message: TextMessage
    kind: Literal["accepted"] = "accepted"


@dataclass(frozen=True)
class SessionMessageAppendUnknown:
    session_id: str
    kind: Literal["unknown"] = "unknown"


@dataclass(frozen=True)
class SessionMessageAppendExpired:
    session_id: str
    expires_at: datetime
    kind: Literal["expired"] = "expired"


@dataclass(frozen=True)
class SessionMessageAppendInvalidMessage:
    session_id: str
    reason: InvalidMessageReason
    kind: Literal["invalid_message"] = "invalid_message"


@dataclass(frozen=True)
class SessionMessageAppendLimitReached:
    session_id: str
    kind: Literal["limit_reached"] = "limit_reached"


@dataclass(frozen=True)
class SessionMessageBusy:
    session_id: str
    kind: Literal["busy"] = "busy"


SessionMessageAppendOutcome = (
    SessionMessageAppendAccepted
    | SessionMessageAppendUnknown
    | SessionMessageAppendExpired
    | SessionMessageAppendInvalidMessage
    | SessionMessageAppendLimitReached
    | SessionMessageBusy
)

