"""Process-local storage for bounded, expiring text sessions."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Generic, Literal, TypeVar, cast
from uuid import uuid4


MAX_MESSAGE_COUNT = 100
MAX_MESSAGE_LENGTH = 4_000

SessionRole = Literal["user", "assistant"]
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


TextSessionReadOutcome = TextSessionReadActive[T] | TextSessionReadUnknown | TextSessionReadExpired


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
    reason: Literal["unsupported_role", "blank_text", "text_too_long"]


@dataclass(frozen=True)
class TextSessionAppendLimitReached:
    kind: Literal["limit_reached"]
    session_id: str


@dataclass(frozen=True)
class TextSessionAppendConflict:
    kind: Literal["conflict"]
    session_id: str


TextSessionAppendOutcome = (
    TextSessionAppendAccepted
    | TextSessionAppendUnknown
    | TextSessionAppendExpired
    | TextSessionAppendInvalidMessage
    | TextSessionAppendLimitReached
    | TextSessionAppendConflict
)


@dataclass(frozen=True)
class _StoredTextSession(Generic[T]):
    expires_at: datetime
    revision: int
    payload: T
    messages: tuple[TextMessage, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_session_id() -> str:
    return str(uuid4())


class EphemeralTextSessionStore(Generic[T]):
    """Retain opaque payloads and bounded text messages for a fixed lifetime."""

    def __init__(
        self,
        lifetime: timedelta,
        clock: Callable[[], datetime] = _utc_now,
        session_id_generator: Callable[[], str] = _new_session_id,
    ) -> None:
        if lifetime <= timedelta():
            raise ValueError("lifetime must be positive")
        self._lifetime = lifetime
        self._clock = clock
        self._session_id_generator = session_id_generator
        self._sessions: dict[str, _StoredTextSession[T]] = {}
        self._lock = RLock()

    def create(self, payload: T) -> TextSessionCreation:
        with self._lock:
            now = _as_utc(self._clock())
            self._discard_expired(now)
            session_id = self._generate_available_session_id()
            expires_at = now + self._lifetime
            self._sessions[session_id] = _StoredTextSession(
                expires_at=expires_at,
                revision=0,
                payload=_copy(payload),
                messages=(),
            )
            return TextSessionCreation(session_id=session_id, expires_at=expires_at)

    def read(self, session_id: str) -> TextSessionReadOutcome[T]:
        with self._lock:
            now = _as_utc(self._clock())
            session = self._sessions.get(session_id)
            if session is None:
                self._discard_expired(now)
                return TextSessionReadUnknown(kind="unknown", session_id=session_id)
            if now >= session.expires_at:
                del self._sessions[session_id]
                self._discard_expired(now)
                return TextSessionReadExpired(
                    kind="expired", session_id=session_id, expires_at=session.expires_at
                )
            self._discard_expired(now, except_session_id=session_id)
            return TextSessionReadActive(
                kind="active",
                session=TextSessionSnapshot(
                    session_id=session_id,
                    expires_at=session.expires_at,
                    revision=session.revision,
                    payload=_copy(session.payload),
                    messages=tuple(_copy(message) for message in session.messages),
                ),
            )

    def append(self, session_id: str, role: object, text: object) -> TextSessionAppendOutcome:
        return self._append(
            session_id, role, text, expected_revision=None, max_message_count=MAX_MESSAGE_COUNT
        )

    def append_with_max_message_count(
        self, session_id: str, role: object, text: object, max_message_count: int
    ) -> TextSessionAppendOutcome:
        if max_message_count < 1 or max_message_count > MAX_MESSAGE_COUNT:
            raise ValueError("max_message_count must be between 1 and MAX_MESSAGE_COUNT")
        return self._append(
            session_id,
            role,
            text,
            expected_revision=None,
            max_message_count=max_message_count,
        )

    def append_if_revision(
        self,
        session_id: str,
        expected_revision: int,
        role: object,
        text: object,
        turn_id: str | None = None,
    ) -> TextSessionAppendOutcome:
        return self._append(
            session_id,
            role,
            text,
            expected_revision=expected_revision,
            max_message_count=MAX_MESSAGE_COUNT,
            turn_id=turn_id,
        )

    def _append(
        self,
        session_id: str,
        role: object,
        text: object,
        expected_revision: int | None,
        max_message_count: int,
        turn_id: str | None = None,
    ) -> TextSessionAppendOutcome:
        with self._lock:
            now = _as_utc(self._clock())
            session = self._sessions.get(session_id)
            if session is None:
                self._discard_expired(now)
                return TextSessionAppendUnknown(kind="unknown", session_id=session_id)
            if now >= session.expires_at:
                del self._sessions[session_id]
                self._discard_expired(now)
                return TextSessionAppendExpired(
                    kind="expired", session_id=session_id, expires_at=session.expires_at
                )
            self._discard_expired(now, except_session_id=session_id)
            if expected_revision is not None and session.revision != expected_revision:
                return TextSessionAppendConflict(kind="conflict", session_id=session_id)
            invalid_reason = _invalid_message_reason(role, text)
            if invalid_reason is not None:
                return TextSessionAppendInvalidMessage(
                    kind="invalid_message", session_id=session_id, reason=invalid_reason
                )
            if len(session.messages) >= max_message_count:
                return TextSessionAppendLimitReached(kind="limit_reached", session_id=session_id)
            message = TextMessage(
                role=cast(SessionRole, role),
                text=cast(str, text),
                turn_id=turn_id,
            )
            self._sessions[session_id] = _StoredTextSession(
                expires_at=session.expires_at,
                revision=session.revision + 1,
                payload=session.payload,
                messages=(*session.messages, message),
            )
            return TextSessionAppendAccepted(kind="accepted", session_id=session_id, message=message)

    def _discard_expired(self, now: datetime, except_session_id: str | None = None) -> None:
        expired_ids = tuple(
            session_id
            for session_id, session in self._sessions.items()
            if session_id != except_session_id and now >= session.expires_at
        )
        for session_id in expired_ids:
            del self._sessions[session_id]

    def _generate_available_session_id(self) -> str:
        while True:
            session_id = self._session_id_generator()
            if session_id and session_id not in self._sessions:
                return session_id


def _invalid_message_reason(
    role: object, text: object
) -> Literal["unsupported_role", "blank_text", "text_too_long"] | None:
    if role not in ("user", "assistant"):
        return "unsupported_role"
    if not isinstance(text, str) or not text.strip():
        return "blank_text"
    if len(text) > MAX_MESSAGE_LENGTH:
        return "text_too_long"
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _copy(value: T) -> T:
    return cast(T, deepcopy(value))
