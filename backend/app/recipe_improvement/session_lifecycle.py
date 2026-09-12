"""Process-local lifecycle storage for recipe-improvement sessions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.recipe_improvement.session_input import RecipeImprovementSessionInput


SESSION_LIFETIME = timedelta(minutes=90)


class RecipeImprovementSessionCreation(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime


class RecipeImprovementSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime
    session_input: RecipeImprovementSessionInput


class RecipeImprovementSessionLookupSuccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["success"] = "success"
    session: RecipeImprovementSessionSnapshot


class RecipeImprovementSessionLookupUnknown(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown"] = "unknown"
    session_id: str


class RecipeImprovementSessionLookupExpired(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["expired"] = "expired"
    session_id: str = Field(min_length=1)
    expires_at: datetime


RecipeImprovementSessionLookupOutcome = (
    RecipeImprovementSessionLookupSuccess
    | RecipeImprovementSessionLookupUnknown
    | RecipeImprovementSessionLookupExpired
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_session_id() -> str:
    return str(uuid4())


class RecipeImprovementSessionStore:
    """Retain validated recipe-improvement inputs for a fixed, short lifetime."""

    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
        session_id_generator: Callable[[], str] = _new_session_id,
    ) -> None:
        self._clock = clock
        self._session_id_generator = session_id_generator
        self._sessions: dict[str, RecipeImprovementSessionSnapshot] = {}
        self._lock = RLock()

    def create(
        self, session_input: RecipeImprovementSessionInput
    ) -> RecipeImprovementSessionCreation:
        """Store an owned validated input and return its generated lifecycle details."""
        with self._lock:
            now = _as_utc(self._clock())
            self._discard_expired(now)
            session_id = self._generate_available_session_id()
            expires_at = now + SESSION_LIFETIME
            self._sessions[session_id] = RecipeImprovementSessionSnapshot(
                session_id=session_id,
                expires_at=expires_at,
                session_input=session_input.model_copy(deep=True),
            )
        return RecipeImprovementSessionCreation(session_id=session_id, expires_at=expires_at)

    def lookup(self, session_id: str) -> RecipeImprovementSessionLookupOutcome:
        """Return an owned active snapshot or an explicit lifecycle outcome."""
        with self._lock:
            now = _as_utc(self._clock())
            session = self._sessions.get(session_id)
            if session is None:
                self._discard_expired(now)
                return RecipeImprovementSessionLookupUnknown(session_id=session_id)
            if now >= session.expires_at:
                del self._sessions[session_id]
                self._discard_expired(now)
                return RecipeImprovementSessionLookupExpired(
                    session_id=session_id,
                    expires_at=session.expires_at,
                )
            self._discard_expired(now, except_session_id=session_id)
            return RecipeImprovementSessionLookupSuccess(session=session.model_copy(deep=True))

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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)
