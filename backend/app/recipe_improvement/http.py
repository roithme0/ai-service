"""HTTP adapters for recipe-improvement sessions and text turns."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.models.text_generation import TextGenerator
from app.recipe_improvement.session_input import (
    AvailableFoodstuffSnapshot,
    RecipeImprovementSessionInputFailure,
    RecipeImprovementSourceSnapshot,
    validate_recipe_improvement_session_input,
)
from app.recipe_improvement.session_lifecycle import (
    RecipeImprovementSessionCreation,
    RecipeImprovementSessionLookupExpired,
    RecipeImprovementSessionLookupSuccess,
    RecipeImprovementSessionStore,
)
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.text_sessions import (
    TextMessage,
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionAppendInvalidMessage,
    TextSessionAppendLimitReached,
)
from app.sessions.text_turns import TextTurnCompleted


router = APIRouter(prefix="/api/v1/recipe-improvement/sessions", tags=["recipe-improvement"])


class RecipeImprovementSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: object
    foodstuffs: object


class RecipeImprovementSessionInputErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["invalid_input"] = "invalid_input"
    issues: tuple[ValidationIssue, ...]


class RecipeImprovementUserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str


class RecipeImprovementSessionReadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime
    source: RecipeImprovementSourceSnapshot
    foodstuffs: tuple[AvailableFoodstuffSnapshot, ...]
    messages: tuple[TextMessage, ...]


def get_recipe_improvement_session_store() -> RecipeImprovementSessionStore:
    return recipe_improvement_session_store


def get_text_generator() -> TextGenerator | None:
    return None


recipe_improvement_session_store = RecipeImprovementSessionStore()


@router.post("", response_model=RecipeImprovementSessionCreation, status_code=201)
def create_recipe_improvement_session(
    request: RecipeImprovementSessionCreateRequest,
    store: RecipeImprovementSessionStore = Depends(get_recipe_improvement_session_store),
) -> RecipeImprovementSessionCreation | JSONResponse:
    outcome = validate_recipe_improvement_session_input(
        _decode_json_decimal_amounts(request.source), request.foodstuffs
    )
    if isinstance(outcome, RecipeImprovementSessionInputFailure):
        return _invalid_input_response(outcome)
    return store.create(outcome.session_input)


@router.get("/{session_id}", response_model=RecipeImprovementSessionReadResponse)
def get_recipe_improvement_session(
    session_id: str,
    store: RecipeImprovementSessionStore = Depends(get_recipe_improvement_session_store),
) -> RecipeImprovementSessionReadResponse | JSONResponse:
    outcome = store.lookup(session_id)
    if isinstance(outcome, RecipeImprovementSessionLookupSuccess):
        return RecipeImprovementSessionReadResponse(
            session_id=outcome.session.session_id,
            expires_at=outcome.session.expires_at,
            source=outcome.session.session_input.source,
            foodstuffs=outcome.session.session_input.foodstuffs,
            messages=outcome.session.messages,
        )
    if isinstance(outcome, RecipeImprovementSessionLookupExpired):
        return JSONResponse(status_code=410, content={"kind": "expired"})
    return JSONResponse(status_code=404, content={"kind": "unknown"})


@router.post("/{session_id}/messages", response_model=TextMessage, status_code=201)
def append_recipe_improvement_user_message(
    session_id: str,
    request: RecipeImprovementUserMessageRequest,
    store: RecipeImprovementSessionStore = Depends(get_recipe_improvement_session_store),
) -> TextMessage | JSONResponse:
    outcome = store.append(session_id, "user", request.text)
    if isinstance(outcome, TextSessionAppendAccepted):
        return outcome.message
    if isinstance(outcome, TextSessionAppendExpired):
        return JSONResponse(status_code=410, content={"kind": "expired"})
    if isinstance(outcome, TextSessionAppendLimitReached):
        return JSONResponse(status_code=409, content={"kind": "limit_reached"})
    if isinstance(outcome, TextSessionAppendInvalidMessage):
        return JSONResponse(status_code=422, content={"kind": "invalid_message"})
    return JSONResponse(status_code=404, content={"kind": "unknown"})


@router.post("/{session_id}/turns", response_model=TextMessage, status_code=201)
async def generate_recipe_improvement_turn(
    session_id: str,
    store: RecipeImprovementSessionStore = Depends(get_recipe_improvement_session_store),
    generator: TextGenerator | None = Depends(get_text_generator),
) -> TextMessage | JSONResponse:
    if generator is None:
        return JSONResponse(status_code=503, content={"kind": "generator_unavailable"})
    outcome = await store.generate_turn(session_id, generator)
    if isinstance(outcome, TextTurnCompleted):
        return outcome.message
    status_code = {
        "unknown": 404,
        "expired": 410,
        "not_ready": 409,
        "limit_reached": 409,
        "conflict": 409,
        "generation_failed": 502,
    }[outcome.kind]
    return JSONResponse(status_code=status_code, content={"kind": outcome.kind})


def _invalid_input_response(
    outcome: RecipeImprovementSessionInputFailure,
) -> JSONResponse:
    response = RecipeImprovementSessionInputErrorResponse(issues=outcome.issues)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


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
    if not decimal_value.is_finite():
        return None
    return decimal_value
