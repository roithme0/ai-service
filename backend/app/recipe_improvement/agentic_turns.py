"""Assemble recipe tools and run one bounded agentic turn."""

from __future__ import annotations

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.proposals import RecipeProposal
from app.recipe_improvement.tools.register_recipe_proposal import (
    RegisterRecipeProposal, RecipeToolFactory, proposal_registration_tool,
)
from app.sessions.text_sessions import TextMessage
from app.sessions.tool_turns import ToolTurnResult, run_tool_turn


MAX_TOOL_ATTEMPTS = 6
MAX_TOOL_SUCCESSES = 3
MAX_PROVIDER_RESPONSES = 8


async def generate_agentic_recipe_turn(
    generator: AgenticGenerator,
    messages: tuple[TextMessage, ...],
    context: str,
    instructions: str,
    register: RegisterRecipeProposal,
    tool_factory: RecipeToolFactory = proposal_registration_tool,
    max_attempts: int = MAX_TOOL_ATTEMPTS,
    max_successes: int = MAX_TOOL_SUCCESSES,
    max_provider_responses: int = MAX_PROVIDER_RESPONSES,
) -> ToolTurnResult[RecipeProposal]:
    return await run_tool_turn(
        generator, messages, context, instructions,
        (tool_factory(register),),
        max_attempts, max_successes, max_provider_responses,
    )
