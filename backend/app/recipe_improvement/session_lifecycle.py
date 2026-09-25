"""Recipe validation and presentation over the shared conversation lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.recipe_improvement.proposals import (
    MAX_PROPOSALS_PER_SESSION,
    PreviousProposalBase,
    ProposalBase,
    ProposalCandidateAccepted,
    ProposalRegistered,
    ProposalRegistrationOutcome,
    ProposalRejected,
    ProposalSessionUnavailable,
    RecipeProposal,
    RecipeProposalPayload,
)
from app.recipe_improvement.resolver import RecipePresentation
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.recipe_improvement.validation import RecipeProposalValidationFailure, validate_recipe_proposal
from app.sessions.conversation import (
    ConversationMessageBusy,
    ConversationReadActive,
    ConversationSessionSettings,
    ConversationSessionStore,
    ConversationStageAccepted,
    ConversationStageRejected,
    ConversationTurnReservation,
    ConversationTurnResult,
    StagedArtifact,
)
from app.sessions.text_sessions import (
    TextMessage,
    TextSessionAppendOutcome,
    TextSessionReadExpired,
    TextSessionReadUnknown,
    TextSessionSnapshot,
)
from app.sessions.tool_turns import ToolTurnResult


SESSION_LIFETIME = timedelta(minutes=90)
RecipeMessageBusy = ConversationMessageBusy


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
    terminal_turn_id: str | None = None
    terminal_turn_kind: str | None = None


@dataclass(frozen=True)
class RecipeTurnResult:
    kind: Literal["completed", "generation_failed", "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]
    turn_id: str
    text: str | None
    proposals: tuple[RecipeProposal, ...]


@dataclass(frozen=True)
class RecipeTurnReservation:
    turn_id: str
    snapshot: TextSessionSnapshot[RecipeImprovementSessionInput]
    previous_proposals: tuple[RecipeProposal, ...]
    shared: ConversationTurnReservation[RecipeImprovementSessionInput, RecipeProposalPayload]


RecipeMessageAppendOutcome = TextSessionAppendOutcome | ConversationMessageBusy


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


def _proposal(artifact: StagedArtifact[RecipeProposalPayload]) -> RecipeProposal:
    return RecipeProposal(
        proposal_id=artifact.artifact_id,
        created_at=artifact.created_at,
        order=artifact.order,
        turn_id=artifact.turn_id,
        base=artifact.payload.base,
        name=artifact.payload.name,
        recipe=artifact.payload.recipe,
    )


def _turn_result(result: ConversationTurnResult[RecipeProposalPayload]) -> RecipeTurnResult:
    return RecipeTurnResult(result.kind, result.turn_id, result.text, tuple(_proposal(a) for a in result.artifacts))


class RecipeImprovementSessionStore:
    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._core = ConversationSessionStore[RecipeImprovementSessionInput, RecipeProposalPayload](
            lifetime=SESSION_LIFETIME, clock=clock
        )

    def create(self, session_input: RecipeImprovementSessionInput) -> RecipeImprovementSessionCreation:
        created = self._core.create(
            session_input, ConversationSessionSettings(max_artifacts=MAX_PROPOSALS_PER_SESSION)
        )
        return RecipeImprovementSessionCreation(session_id=created.session_id, expires_at=created.expires_at)

    def lookup(self, session_id: str) -> RecipeImprovementSessionLookupOutcome:
        outcome = self._core.read(session_id)
        if isinstance(outcome, ConversationReadActive):
            snapshot = outcome.snapshot
            return RecipeImprovementSessionLookupSuccess(
                session=RecipeImprovementSessionSnapshot(
                    session_id=snapshot.session.session_id,
                    expires_at=snapshot.session.expires_at,
                    session_input=snapshot.session.payload,
                    messages=snapshot.session.messages,
                    proposals=tuple(_proposal(a) for a in snapshot.artifacts),
                    terminal_turn_id=snapshot.terminal_turn_id,
                    terminal_turn_kind=snapshot.terminal_turn_kind,
                )
            )
        if isinstance(outcome, TextSessionReadExpired):
            return RecipeImprovementSessionLookupExpired(session_id=outcome.session_id, expires_at=outcome.expires_at)
        assert isinstance(outcome, TextSessionReadUnknown)
        return RecipeImprovementSessionLookupUnknown(session_id=outcome.session_id)

    def validate_proposal_candidate(
        self, session_id: str, base: ProposalBase, candidate: object, turn_id: str
    ) -> ProposalCandidateAccepted | ProposalRegistrationOutcome:
        view = self._core.inspect_turn(session_id, turn_id)
        if isinstance(view, ConversationStageRejected):
            return ProposalSessionUnavailable(kind="expired" if view.kind == "expired" else "unknown")
        if isinstance(base, PreviousProposalBase) and not any(
            artifact.artifact_id == base.proposal_id for artifact in view.artifacts
        ):
            return ProposalRejected(reason="invalid_base")
        if len(view.artifacts) >= view.max_artifacts:
            return ProposalRejected(reason="limit_reached")
        session_input = view.snapshot.payload
        validation = validate_recipe_proposal(
            session_input.source.model_dump(), session_input.availability_reference_index, candidate
        )
        if isinstance(validation, RecipeProposalValidationFailure):
            return ProposalRejected(reason="invalid_candidate", issues=validation.issues)
        return ProposalCandidateAccepted(candidate=validation.candidate)

    def register_resolved_proposal(
        self, session_id: str, base: ProposalBase, name: str, recipe: RecipePresentation, turn_id: str
    ) -> ProposalRegistrationOutcome:
        required_id = base.proposal_id if isinstance(base, PreviousProposalBase) else None
        staged = self._core.stage_artifact(
            session_id, turn_id, RecipeProposalPayload(base=base, name=name, recipe=recipe), required_id
        )
        if isinstance(staged, ConversationStageAccepted):
            return ProposalRegistered(proposal=_proposal(staged.artifact))
        if staged.kind == "missing_reference":
            return ProposalRejected(reason="invalid_base")
        if staged.kind == "limit_reached":
            return ProposalRejected(reason="limit_reached")
        return ProposalSessionUnavailable(kind="expired" if staged.kind == "expired" else "unknown")

    def append_user_message(self, session_id: str, text: object) -> RecipeMessageAppendOutcome:
        return self._core.append_user_message(session_id, text)

    def reserve_turn(self, session_id: str) -> RecipeTurnReservation | RecipeTurnResult:
        result = self._core.reserve_turn(session_id)
        if isinstance(result, ConversationTurnResult):
            return _turn_result(result)
        return RecipeTurnReservation(
            turn_id=result.turn_id,
            snapshot=result.snapshot,
            previous_proposals=tuple(_proposal(a) for a in result.previous_artifacts),
            shared=result,
        )

    def complete_turn(
        self, session_id: str, reservation: RecipeTurnReservation, result: ToolTurnResult[RecipeProposal]
    ) -> RecipeTurnResult:
        return _turn_result(self._core.complete_turn(session_id, reservation.shared, result.kind, result.text))

    def fail_turn(self, session_id: str, reservation: RecipeTurnReservation) -> RecipeTurnResult:
        return _turn_result(self._core.fail_turn(session_id, reservation.shared))
