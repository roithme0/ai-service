"""Immutable, session-scoped recipe proposal records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.recipe_improvement.resolver import RecipePresentation
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.conversation import StagedArtifact


MAX_PROPOSALS_PER_SESSION = 20


class SourceProposalBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["source"] = "source"


class PreviousProposalBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["proposal"] = "proposal"
    proposal_id: str = Field(min_length=1)


ProposalBase = SourceProposalBase | PreviousProposalBase


class RecipeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str
    created_at: datetime
    order: int = Field(ge=1)
    base: ProposalBase
    name: str = Field(min_length=1, max_length=200)
    recipe: RecipePresentation
    turn_id: str = Field(min_length=1)


class RecipeProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base: ProposalBase
    name: str = Field(min_length=1, max_length=200)
    recipe: RecipePresentation


class ProposalRegistered(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["registered"] = "registered"
    proposal: RecipeProposal


class ProposalRejected(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["rejected"] = "rejected"
    reason: Literal[
        "invalid_base", "invalid_candidate", "limit_reached", "resolver_unavailable"
    ]
    issues: tuple[ValidationIssue, ...] = ()
    retryable: bool = False


class ProposalSessionUnavailable(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown", "expired"]


ProposalRegistrationOutcome = ProposalRegistered | ProposalRejected | ProposalSessionUnavailable


def proposal_from_artifact(artifact: StagedArtifact[RecipeProposalPayload]) -> RecipeProposal:
    return RecipeProposal(
        proposal_id=artifact.artifact_id,
        created_at=artifact.created_at,
        order=artifact.order,
        turn_id=artifact.turn_id,
        base=artifact.payload.base,
        name=artifact.payload.name,
        recipe=artifact.payload.recipe,
    )
