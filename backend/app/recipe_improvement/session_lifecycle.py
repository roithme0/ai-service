"""Recipe-improvement adapter for the shared ephemeral text-session core."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.text_generation import TextGenerator
from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.recipe_improvement.proposals import (
    MAX_PROPOSALS_PER_SESSION,
    PreviousProposalBase,
    ProposalBase,
    ProposalRegistered,
    ProposalRegistrationOutcome,
    ProposalRejected,
    ProposalSessionUnavailable,
    RecipeProposal,
)
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.recipe_improvement.validation import RecipeProposalValidationFailure, validate_recipe_proposal
from app.sessions.text_sessions import (
    EphemeralTextSessionStore,
    MAX_MESSAGE_COUNT,
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
    proposals: tuple[RecipeProposal, ...] = ()


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
        self._clock = clock
        self._proposals: dict[str, tuple[RecipeProposal, ...]] = {}
        self._lock = RLock()

    def create(
        self, session_input: RecipeImprovementSessionInput
    ) -> RecipeImprovementSessionCreation:
        with self._lock:
            for session_id in tuple(self._proposals):
                if not isinstance(self._core.read(session_id), TextSessionReadActive):
                    del self._proposals[session_id]
            created = self._core.create(session_input)
            return RecipeImprovementSessionCreation(
                session_id=created.session_id, expires_at=created.expires_at
            )

    def lookup(self, session_id: str) -> RecipeImprovementSessionLookupOutcome:
        with self._lock:
            outcome = self._core.read(session_id)
            if isinstance(outcome, TextSessionReadActive):
                return RecipeImprovementSessionLookupSuccess(
                    session=RecipeImprovementSessionSnapshot(
                        session_id=outcome.session.session_id,
                        expires_at=outcome.session.expires_at,
                        session_input=outcome.session.payload,
                        messages=outcome.session.messages,
                        proposals=self._proposals.get(session_id, ()),
                    )
                )
            self._proposals.pop(session_id, None)
            if isinstance(outcome, TextSessionReadExpired):
                return RecipeImprovementSessionLookupExpired(
                    session_id=outcome.session_id, expires_at=outcome.expires_at
                )
            assert isinstance(outcome, TextSessionReadUnknown)
            return RecipeImprovementSessionLookupUnknown(session_id=outcome.session_id)

    def register_proposal(
        self, session_id: str, base: ProposalBase, candidate: object
    ) -> ProposalRegistrationOutcome:
        with self._lock:
            outcome = self._core.read(session_id)
            if not isinstance(outcome, TextSessionReadActive):
                self._proposals.pop(session_id, None)
                return ProposalSessionUnavailable(kind=outcome.kind)

            proposals = self._proposals.get(session_id, ())
            if isinstance(base, PreviousProposalBase) and not any(
                proposal.proposal_id == base.proposal_id for proposal in proposals
            ):
                return ProposalRejected(reason="invalid_base")
            if len(proposals) >= MAX_PROPOSALS_PER_SESSION:
                return ProposalRejected(reason="limit_reached")

            session_input = outcome.session.payload
            validation = validate_recipe_proposal(
                session_input.source.model_dump(),
                session_input.availability_reference_index,
                candidate,
            )
            if isinstance(validation, RecipeProposalValidationFailure):
                return ProposalRejected(reason="invalid_candidate", issues=validation.issues)

            proposal = RecipeProposal(
                proposal_id=str(uuid4()),
                created_at=self._clock().astimezone(UTC),
                order=len(proposals) + 1,
                base=base,
                recipe=validation.candidate,
            )
            self._proposals[session_id] = (*proposals, proposal)
            return ProposalRegistered(proposal=proposal)

    def append_user_message(self, session_id: str, text: object) -> TextSessionAppendOutcome:
        return self._core.append_with_max_message_count(
            session_id, "user", text, MAX_MESSAGE_COUNT - 1
        )

    async def generate_turn(self, session_id: str, generator: TextGenerator) -> TextTurnOutcome:
        outcome = self._core.read(session_id)
        context = recipe_context(outcome.session.payload) if isinstance(outcome, TextSessionReadActive) else None
        return await generate_assistant_turn(
            self._core, session_id, generator, context, RECIPE_IMPROVEMENT_INSTRUCTIONS
        )
