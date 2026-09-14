"""Assemble recipe tools and run one bounded agentic turn."""

from __future__ import annotations

from collections.abc import Callable

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.proposals import ProposalRegistrationOutcome, RecipeProposal
from app.recipe_improvement.tools.register_recipe_proposal import proposal_registration_tool
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
    register: Callable[[object, object], ProposalRegistrationOutcome],
) -> ToolTurnResult[RecipeProposal]:
    return await run_tool_turn(
        generator, messages, context, instructions,
        (proposal_registration_tool(register),),
        MAX_TOOL_ATTEMPTS, MAX_TOOL_SUCCESSES, MAX_PROVIDER_RESPONSES,
    )
