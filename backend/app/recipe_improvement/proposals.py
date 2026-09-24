"""Immutable, session-scoped recipe proposal records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.recipe_improvement.recipe import RecipeProposalCandidate
from app.recipe_improvement.resolver import RecipePresentation
from app.recipe_improvement.validation import ValidationIssue


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


class ProposalCandidateAccepted(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["candidate_accepted"] = "candidate_accepted"
    candidate: RecipeProposalCandidate


class ProposalSessionUnavailable(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown", "expired"]


ProposalRegistrationOutcome = ProposalRegistered | ProposalRejected | ProposalSessionUnavailable
