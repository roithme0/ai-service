"""Validate and resolve recipe proposal artifacts outside the conversation store."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from app.recipe_improvement.proposals import (
    PreviousProposalBase, ProposalBase, ProposalRejected, RecipeProposalPayload,
)
from app.recipe_improvement.resolver import RecipePresentationResolver, RecipeResolutionError
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.recipe_improvement.validation import RecipeProposalValidationFailure, validate_recipe_proposal
from app.sessions.artifacts import ArtifactPrepared, ArtifactPreparationRejected
from app.sessions.conversation import ConversationTurnView


@dataclass(frozen=True)
class RecipeProposalAttempt:
    base: object
    candidate: object


class RecipeProposalHandler:
    def __init__(self, resolver: RecipePresentationResolver) -> None:
        self._resolver = resolver

    async def prepare(
        self,
        view: ConversationTurnView[RecipeImprovementSessionInput, RecipeProposalPayload],
        candidate: object,
    ) -> ArtifactPrepared[RecipeProposalPayload] | ArtifactPreparationRejected[ProposalRejected]:
        if not isinstance(candidate, RecipeProposalAttempt):
            return ArtifactPreparationRejected(ProposalRejected(reason="invalid_candidate"))
        try:
            base = TypeAdapter(ProposalBase).validate_python(candidate.base)
        except ValidationError:
            return ArtifactPreparationRejected(ProposalRejected(reason="invalid_base"))
        if isinstance(base, PreviousProposalBase) and not any(
            artifact.artifact_id == base.proposal_id for artifact in view.artifacts
        ):
            return ArtifactPreparationRejected(ProposalRejected(reason="invalid_base"))
        if len(view.artifacts) >= view.max_artifacts:
            return ArtifactPreparationRejected(ProposalRejected(reason="limit_reached"))
        session_input = view.snapshot.payload
        validation = validate_recipe_proposal(
            session_input.source.model_dump(), session_input.availability_reference_index,
            candidate.candidate,
        )
        if isinstance(validation, RecipeProposalValidationFailure):
            return ArtifactPreparationRejected(
                ProposalRejected(reason="invalid_candidate", issues=validation.issues)
            )
        try:
            presentation = await self._resolver.resolve(validation.candidate)
        except RecipeResolutionError as error:
            return ArtifactPreparationRejected(ProposalRejected(
                reason="resolver_unavailable" if error.retryable else "invalid_candidate",
                retryable=error.retryable,
            ), stage="resolver")
        return ArtifactPrepared(
            RecipeProposalPayload(base=base, name=validation.candidate.name, recipe=presentation),
            base.proposal_id if isinstance(base, PreviousProposalBase) else None,
        )
