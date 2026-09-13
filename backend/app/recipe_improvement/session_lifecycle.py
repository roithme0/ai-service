"""Recipe-improvement adapter for the shared ephemeral text-session core."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.text_generation import TextGenerator
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.sessions.text_sessions import (
    EphemeralTextSessionStore,
    TextMessage,
    TextSessionAppendOutcome,
    TextSessionReadActive,
    TextSessionReadExpired,
    TextSessionReadUnknown,
)
from app.sessions.text_turns import TextTurnOutcome, generate_assistant_turn


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
    messages: tuple[TextMessage, ...] = ()


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


class RecipeImprovementSessionStore:
    """Apply the recipe-improvement lifetime policy to the shared session core."""

    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._core = EphemeralTextSessionStore[RecipeImprovementSessionInput](
            lifetime=SESSION_LIFETIME, clock=clock
        )

    def create(
        self, session_input: RecipeImprovementSessionInput
    ) -> RecipeImprovementSessionCreation:
        created = self._core.create(session_input)
        return RecipeImprovementSessionCreation(
            session_id=created.session_id, expires_at=created.expires_at
        )

    def lookup(self, session_id: str) -> RecipeImprovementSessionLookupOutcome:
        outcome = self._core.read(session_id)
        if isinstance(outcome, TextSessionReadActive):
            return RecipeImprovementSessionLookupSuccess(
                session=RecipeImprovementSessionSnapshot(
                    session_id=outcome.session.session_id,
                    expires_at=outcome.session.expires_at,
                    session_input=outcome.session.payload,
                    messages=outcome.session.messages,
                )
            )
        if isinstance(outcome, TextSessionReadExpired):
            return RecipeImprovementSessionLookupExpired(
                session_id=outcome.session_id, expires_at=outcome.expires_at
            )
        assert isinstance(outcome, TextSessionReadUnknown)
        return RecipeImprovementSessionLookupUnknown(session_id=outcome.session_id)

    def append(self, session_id: str, role: object, text: object) -> TextSessionAppendOutcome:
        return self._core.append(session_id, role, text)

    async def generate_turn(self, session_id: str, generator: TextGenerator) -> TextTurnOutcome:
        return await generate_assistant_turn(self._core, session_id, generator)
