"""Prepare model input and orchestrate one recipe-improvement turn."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.agentic_turns import generate_agentic_recipe_turn
from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.recipe_improvement.proposals import ProposalBase, ProposalRegistrationOutcome, ProposalRejected
from app.recipe_improvement.session_lifecycle import (
    RecipeImprovementSessionStore,
    RecipeTurnResult,
)


async def generate_recipe_turn(
    store: RecipeImprovementSessionStore,
    session_id: str,
    generator: AgenticGenerator,
) -> RecipeTurnResult:
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, RecipeTurnResult):
        return reservation

    try:
        context = recipe_context(reservation.snapshot.payload, reservation.previous_proposals)

        def register_from_tool(base: object, candidate: object) -> ProposalRegistrationOutcome:
            try:
                validated_base = TypeAdapter(ProposalBase).validate_python(base)
            except ValidationError:
                return ProposalRejected(reason="invalid_base")
            return store.register_proposal(session_id, validated_base, candidate, reservation.turn_id)

        result = await generate_agentic_recipe_turn(
            generator,
            reservation.snapshot.messages,
            context,
            RECIPE_IMPROVEMENT_INSTRUCTIONS,
            register_from_tool,
        )
        return store.complete_turn(session_id, reservation, result)
    except Exception:
        return store.fail_turn(session_id, reservation)
