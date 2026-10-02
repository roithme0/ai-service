"""Kochwiki agent configuration and input normalization."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Never

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.session_input import (
    RecipeImprovementSessionInput, RecipeImprovementSessionInputFailure,
    validate_recipe_improvement_session_input,
)
from app.recipe_improvement.session_lifecycle import (
    MAX_ARTIFACTS_PER_SESSION, RecipeImprovementSessionStore, new_recipe_session_store,
)
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.agent_service import AgentInputAccepted, AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationSessionSettings
from app.sessions.instructions import CONVERSATION_INSTRUCTIONS
from app.sessions.model_turns import MAX_PROVIDER_RESPONSES, MAX_TOOL_ATTEMPTS, ModelTurnStrategy
from app.sessions.tools import ToolSource


@dataclass(frozen=True)
class KochwikiSessionInput:
    source: object
    foodstuffs: object


KochwikiAgent = ConfiguredAgentService[
    KochwikiSessionInput, RecipeImprovementSessionInput, Never, ValidationIssue
]


def validate_kochwiki_input(
    value: KochwikiSessionInput,
) -> AgentInputAccepted[RecipeImprovementSessionInput] | AgentInputRejected[ValidationIssue]:
    result = validate_recipe_improvement_session_input(
        _decode_json_decimal_amounts(value.source), value.foodstuffs,
    )
    if isinstance(result, RecipeImprovementSessionInputFailure):
        return AgentInputRejected(result.issues)
    return AgentInputAccepted(result.session_input)


def create_kochwiki_agent(
    generator: AgenticGenerator,
    store: RecipeImprovementSessionStore | None = None,
    *,
    instructions: str = CONVERSATION_INSTRUCTIONS,
    max_artifacts: int = MAX_ARTIFACTS_PER_SESSION,
    max_tool_attempts: int = MAX_TOOL_ATTEMPTS,
    max_provider_responses: int = MAX_PROVIDER_RESPONSES,
    tool_sources: tuple[ToolSource[Never], ...] = (),
) -> KochwikiAgent:
    owned_store = store if store is not None else new_recipe_session_store()
    return ConfiguredAgentService(
        owned_store, validate_kochwiki_input,
        ModelTurnStrategy(
            owned_store, generator, recipe_context, tool_sources,
            instructions=instructions, max_attempts=max_tool_attempts,
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
