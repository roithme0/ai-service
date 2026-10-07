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
    kind: Literal["active"]
    session: SessionSnapshot[T]


@dataclass(frozen=True)
class SessionReadUnknown:
    kind: Literal["unknown"]
    session_id: str


@dataclass(frozen=True)
class SessionReadExpired:
    kind: Literal["expired"]
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionMessageAppendAccepted:
    kind: Literal["accepted"]
    session_id: str
    message: TextMessage


@dataclass(frozen=True)
class SessionMessageAppendUnknown:
    kind: Literal["unknown"]
    session_id: str


@dataclass(frozen=True)
class SessionMessageAppendExpired:
    kind: Literal["expired"]
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionMessageAppendInvalidMessage:
    kind: Literal["invalid_message"]
    session_id: str
    reason: InvalidMessageReason


@dataclass(frozen=True)
class SessionMessageAppendLimitReached:
    kind: Literal["limit_reached"]
    session_id: str


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

