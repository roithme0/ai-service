"""Recipe improvement agent configuration and input normalization."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.agentic_turns import MAX_PROVIDER_RESPONSES, MAX_TOOL_ATTEMPTS, MAX_TOOL_SUCCESSES
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.recipe_improvement.proposals import (
    MAX_PROPOSALS_PER_SESSION, RecipeProposalPayload,
)
from app.recipe_improvement.resolver import RecipePresentationResolver
from app.recipe_improvement.session_input import (
    RecipeImprovementSessionInput, RecipeImprovementSessionInputFailure,
    validate_recipe_improvement_session_input,
)
from app.recipe_improvement.session_lifecycle import RecipeImprovementSessionStore, new_recipe_session_store
from app.recipe_improvement.tools.register_recipe_proposal import (
    RecipeToolFactory, proposal_registration_tool,
)
from app.recipe_improvement.turn_service import RecipeTurnStrategy
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.agent_service import AgentInputAccepted, AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationSessionSettings


@dataclass(frozen=True)
class RecipeSessionInput:
    source: object
    foodstuffs: object


RecipeAgent = ConfiguredAgentService[
    RecipeSessionInput, RecipeImprovementSessionInput, RecipeProposalPayload, ValidationIssue
]


def validate_recipe_input(
    value: RecipeSessionInput,
) -> AgentInputAccepted[RecipeImprovementSessionInput] | AgentInputRejected[ValidationIssue]:
    result = validate_recipe_improvement_session_input(
        _decode_json_decimal_amounts(value.source), value.foodstuffs,
    )
    if isinstance(result, RecipeImprovementSessionInputFailure):
        return AgentInputRejected(result.issues)
    return AgentInputAccepted(result.session_input)


def create_recipe_agent(
    generator: AgenticGenerator,
    resolver: RecipePresentationResolver,
    store: RecipeImprovementSessionStore | None = None,
    *,
    instructions: str = RECIPE_IMPROVEMENT_INSTRUCTIONS,
    max_artifacts: int = MAX_PROPOSALS_PER_SESSION,
    max_tool_attempts: int = MAX_TOOL_ATTEMPTS,
    max_tool_successes: int = MAX_TOOL_SUCCESSES,
    max_provider_responses: int = MAX_PROVIDER_RESPONSES,
    tool_factory: RecipeToolFactory = proposal_registration_tool,
) -> RecipeAgent:
    owned_store = store if store is not None else new_recipe_session_store()
    return ConfiguredAgentService(
        owned_store, validate_recipe_input,
        RecipeTurnStrategy(
            owned_store, generator, resolver, instructions, tool_factory,
            max_attempts=max_tool_attempts, max_successes=max_tool_successes,
            max_provider_responses=max_provider_responses,
        ),
        ConversationSessionSettings(max_artifacts=max_artifacts),
    )


def _decode_json_decimal_amounts(source: object) -> object:
    if not isinstance(source, dict):
        return source
    recipe = source.get("recipe")
    if not isinstance(recipe, dict):
        return source
    ingredients = recipe.get("ingredients")
    if not isinstance(ingredients, list):
        return source
    decoded_source = dict(source)
    decoded_recipe = dict(recipe)
    decoded_ingredients: list[object] = []
    for ingredient in ingredients:
        if isinstance(ingredient, dict):
            decoded_ingredient = dict(ingredient)
            amount = _decode_json_decimal(ingredient.get("amount"))
            if amount is not None:
                decoded_ingredient["amount"] = amount
            decoded_ingredients.append(decoded_ingredient)
        else:
            decoded_ingredients.append(ingredient)
    decoded_recipe["ingredients"] = decoded_ingredients
    decoded_source["recipe"] = decoded_recipe
    return decoded_source


def _decode_json_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    return decimal_value if decimal_value.is_finite() else None
