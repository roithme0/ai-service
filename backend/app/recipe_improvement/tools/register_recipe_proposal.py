"""Registration tool for complete recipe proposals."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation

from app.recipe_improvement.proposals import ProposalRegistered, ProposalRegistrationOutcome, RecipeProposal
from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation


type RegisterRecipeProposal = Callable[[object, object], Awaitable[ProposalRegistrationOutcome]]
type RecipeToolFactory = Callable[[RegisterRecipeProposal], RegisteredTool[RecipeProposal]]


_BASE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": ["source", "proposal"]},
        "proposal_id": {"type": "string"},
    },
}

_INGREDIENT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["index", "amount", "foodstuff_reference"],
    "properties": {
        "index": {"type": "integer"},
        "amount": {"type": "string"},
        "foodstuff_reference": {"type": "integer"},
    },
}

_STEP_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["index", "description"],
    "properties": {
        "index": {"type": "integer"},
        "description": {"type": "string"},
    },
}

_CANDIDATE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "servings", "preparation_time", "ingredients", "steps"],
    "properties": {
        "name": {"type": "string"},
        "servings": {"type": "integer"},
        "preparation_time": {"type": ["integer", "null"]},
        "ingredients": {"type": "array", "items": _INGREDIENT_SCHEMA},
        "steps": {"type": "array", "items": _STEP_SCHEMA},
    },
}

REGISTER_TOOL_SCHEMA: dict[str, object] = {
    "type": "function",
    "name": "register_recipe_proposal",
    "description": "Register a complete recipe proposal based on the source or an earlier proposal.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["base", "candidate"],
        "properties": {"base": _BASE_SCHEMA, "candidate": _CANDIDATE_SCHEMA},
    },
    "strict": False,
}


def _decode_arguments(arguments: str) -> tuple[object, object] | None:
    try:
        value = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    if (not isinstance(value, dict) or set(value) != {"base", "candidate"}
        or not isinstance(value.get("base"), dict)):
        return None
    candidate = value.get("candidate")
    if not isinstance(candidate, dict):
        return None
    candidate_copy = dict(candidate)
    ingredients = candidate_copy.get("ingredients")
    if isinstance(ingredients, list):
        converted: list[object] = []
        for ingredient in ingredients:
            if not isinstance(ingredient, dict):
                converted.append(ingredient)
                continue
            item = dict(ingredient)
            amount = item.get("amount")
            if isinstance(amount, (str, int, float)) and not isinstance(amount, bool):
                try:
                    item["amount"] = Decimal(str(amount))
                except InvalidOperation:
                    pass
            converted.append(item)
        candidate_copy["ingredients"] = converted
    return value["base"], candidate_copy


async def _execute_registration(
    call: ToolInvocation,
    register: RegisterRecipeProposal,
) -> ToolExecution[RecipeProposal]:
    decoded = _decode_arguments(call.arguments)
    if decoded is None:
        return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
    outcome = await register(*decoded)
    if isinstance(outcome, ProposalRegistered):
        return ToolExecution(
            json.dumps({
                "kind": "registered",
                "proposal": outcome.proposal.model_dump(mode="json"),
            }),
            outcome.proposal,
        )
    if outcome.kind == "rejected":
        return ToolExecution(json.dumps({
            "kind": "rejected", "reason": outcome.reason,
            "issues": [issue.model_dump(mode="json") for issue in outcome.issues],
            "retryable": outcome.retryable,
        }))
    return ToolExecution(json.dumps({"kind": outcome.kind}))


def proposal_registration_tool(
    register: RegisterRecipeProposal,
) -> RegisteredTool[RecipeProposal]:
    return RegisteredTool(
        name="register_recipe_proposal",
        schema=REGISTER_TOOL_SCHEMA,
        execute=lambda call: _execute_registration(call, register),
    )
