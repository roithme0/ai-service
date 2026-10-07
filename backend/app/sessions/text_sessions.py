"""Shared message projections and session operation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, TypeVar

from app.agents.output_items import MAX_MESSAGE_LENGTH as MAX_MESSAGE_LENGTH


MAX_MESSAGE_COUNT = 200


SessionRole = Literal["user", "assistant"]
InvalidMessageReason = Literal["blank_text", "text_too_long"]
T = TypeVar("T")


@dataclass(frozen=True)
class TextSessionCreation:
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class TextMessage:
    role: SessionRole
    text: str
    turn_id: str | None = None


@dataclass(frozen=True)
class TextSessionSnapshot(Generic[T]):
    session_id: str
    expires_at: datetime
    revision: int
    payload: T
    messages: tuple[TextMessage, ...]


@dataclass(frozen=True)
class TextSessionReadActive(Generic[T]):
    kind: Literal["active"]
    session: TextSessionSnapshot[T]


@dataclass(frozen=True)
class TextSessionReadUnknown:
    kind: Literal["unknown"]
    session_id: str


@dataclass(frozen=True)
class TextSessionReadExpired:
    kind: Literal["expired"]
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class TextSessionAppendAccepted:
    kind: Literal["accepted"]
    session_id: str
    message: TextMessage


@dataclass(frozen=True)
class TextSessionAppendUnknown:
    kind: Literal["unknown"]
    session_id: str


@dataclass(frozen=True)
class TextSessionAppendExpired:
    kind: Literal["expired"]
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class TextSessionAppendInvalidMessage:
    kind: Literal["invalid_message"]
    session_id: str
    reason: InvalidMessageReason


@dataclass(frozen=True)
class TextSessionAppendLimitReached:
    kind: Literal["limit_reached"]
    session_id: str


TextSessionAppendOutcome = (
    TextSessionAppendAccepted
    | TextSessionAppendUnknown
    | TextSessionAppendExpired
    | TextSessionAppendInvalidMessage
    | TextSessionAppendLimitReached
)

