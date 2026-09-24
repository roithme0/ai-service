"""Prepare model input and orchestrate one recipe-improvement turn."""

from __future__ import annotations

import asyncio
import logging

from pydantic import TypeAdapter, ValidationError

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.agentic_turns import generate_agentic_recipe_turn
from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.recipe_improvement.proposals import (
    ProposalBase,
    ProposalCandidateAccepted,
    ProposalRegistrationOutcome,
    ProposalRejected,
)
from app.recipe_improvement.resolver import RecipePresentationResolver, RecipeResolutionError
from app.recipe_improvement.session_lifecycle import (
    RecipeImprovementSessionStore,
    RecipeTurnResult,
)

logger = logging.getLogger(__name__)


async def generate_recipe_turn(
    store: RecipeImprovementSessionStore,
    session_id: str,
    generator: AgenticGenerator,
    resolver: RecipePresentationResolver,
) -> RecipeTurnResult:
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, RecipeTurnResult):
        return reservation

    try:
        context = recipe_context(reservation.snapshot.payload, reservation.previous_proposals)

        async def register_from_tool(
            base: object, candidate: object
        ) -> ProposalRegistrationOutcome:
            try:
                validated_base = TypeAdapter(ProposalBase).validate_python(base)
            except ValidationError:
                return ProposalRejected(reason="invalid_base")
            validated = store.validate_proposal_candidate(
                session_id, validated_base, candidate, reservation.turn_id
            )
            if not isinstance(validated, ProposalCandidateAccepted):
                return validated
            try:
                presentation = await resolver.resolve(validated.candidate)
            except RecipeResolutionError as error:
                return ProposalRejected(
                    reason="resolver_unavailable" if error.retryable else "invalid_candidate",
                    retryable=error.retryable,
                )
            return store.register_resolved_proposal(
                session_id,
                validated_base,
                validated.candidate.name,
                presentation,
                reservation.turn_id,
            )

        result = await generate_agentic_recipe_turn(
            generator,
            reservation.snapshot.messages,
            context,
            RECIPE_IMPROVEMENT_INSTRUCTIONS,
            register_from_tool,
        )
        return store.complete_turn(session_id, reservation, result)
    except asyncio.CancelledError:
        store.fail_turn(session_id, reservation)
        raise
    except Exception:
        logger.exception(
            "Recipe turn generation failed (session_id=%s, turn_id=%s)",
            session_id,
            reservation.turn_id,
        )
        return store.fail_turn(session_id, reservation)
