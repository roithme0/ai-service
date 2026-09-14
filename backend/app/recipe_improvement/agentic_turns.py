"""Recipe-specific proposal tool definition and registration boundary."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from app.models.agentic_generation import AgenticGenerator, AgenticToolCall
from app.recipe_improvement.proposals import ProposalRegistered, ProposalRegistrationOutcome, RecipeProposal
from app.sessions.text_sessions import TextMessage
from app.sessions.tool_turns import RegisteredTool, ToolExecution, ToolTurnResult, run_tool_turn


MAX_TOOL_ATTEMPTS = 6
MAX_TOOL_SUCCESSES = 3
MAX_PROVIDER_RESPONSES = 8

REGISTER_TOOL_SCHEMA: dict[str, object] = {
    "type": "function",
    "name": "register_recipe_proposal",
    "description": "Register a complete recipe proposal based on the source or an earlier proposal.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["base", "candidate"],
        "properties": {
            "base": {"type": "object", "additionalProperties": False,
                     "required": ["kind"], "properties": {
                         "kind": {"type": "string", "enum": ["source", "proposal"]},
                         "proposal_id": {"type": "string"}}},
            "candidate": {"type": "object", "additionalProperties": False,
                          "required": ["name", "servings", "ingredients", "steps"],
                          "properties": {
                              "name": {"type": "string"}, "servings": {"type": "integer"},
                              "preparation_time": {"type": ["integer", "null"]},
                              "origin_name": {"type": ["string", "null"]},
                              "origin_url": {"type": ["string", "null"]},
                              "ingredients": {"type": "array", "items": {"type": "object",
                                  "additionalProperties": False,
                                  "required": ["index", "amount", "foodstuff_reference"],
                                  "properties": {"index": {"type": "integer"},
                                                 "amount": {"type": "string"},
                                                 "foodstuff_reference": {"type": "integer"}}}},
                              "steps": {"type": "array", "items": {"type": "object",
                                  "additionalProperties": False,
                                  "required": ["index", "description"],
                                  "properties": {"index": {"type": "integer"},
                                                 "description": {"type": "string"}}}},
                          }},
        },
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


def _execute_registration(
    call: AgenticToolCall,
    register: Callable[[object, object], ProposalRegistrationOutcome],
) -> ToolExecution[RecipeProposal]:
    decoded = _decode_arguments(call.arguments)
    if decoded is None:
        return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
    outcome = register(*decoded)
    if isinstance(outcome, ProposalRegistered):
        return ToolExecution(
            json.dumps({"kind": "registered", "proposal_id": outcome.proposal.proposal_id}),
            outcome.proposal,
        )
    if outcome.kind == "rejected":
        return ToolExecution(json.dumps({
            "kind": "rejected", "reason": outcome.reason,
            "issues": [issue.model_dump(mode="json") for issue in outcome.issues],
        }))
    return ToolExecution(json.dumps({"kind": outcome.kind}))


async def generate_agentic_recipe_turn(
    generator: AgenticGenerator,
    messages: tuple[TextMessage, ...],
    context: str,
    instructions: str,
    register: Callable[[object, object], ProposalRegistrationOutcome],
) -> ToolTurnResult[RecipeProposal]:
    return await run_tool_turn(
        generator, messages, context, instructions,
        (RegisteredTool(
            name="register_recipe_proposal", schema=REGISTER_TOOL_SCHEMA,
            execute=lambda call: _execute_registration(call, register),
        ),),
        MAX_TOOL_ATTEMPTS, MAX_TOOL_SUCCESSES, MAX_PROVIDER_RESPONSES,
    )
