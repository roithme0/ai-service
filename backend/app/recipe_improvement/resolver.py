"""Kochwiki recipe-presentation resolver boundary."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kochwiki_contract import (
    FoodstuffSummaryOut,
    RecipePresentationIngredientOut,
    RecipePresentationIngredientResolve,
    RecipePresentationOut,
    RecipePresentationResolve,
    RecipePresentationStepOut,
    RecipePresentationStepResolve,
)
from kochwiki_contract.common import NonnegativeJsonDecimal
from pydantic import BaseModel, ConfigDict, field_validator

from app.recipe_improvement.recipe import RecipeProposalCandidate


class FoodstuffSummary(FoodstuffSummaryOut):
    model_config = ConfigDict(frozen=True)


class RecipePresentationIngredient(RecipePresentationIngredientOut):
    model_config = ConfigDict(frozen=True)

    foodstuff: FoodstuffSummary


class RecipePresentationStep(RecipePresentationStepOut):
    model_config = ConfigDict(frozen=True)


class RecipePresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    servings: int
    preptime: int | None
    kcal: NonnegativeJsonDecimal | None
    carbs: NonnegativeJsonDecimal | None
    protein: NonnegativeJsonDecimal | None
    fat: NonnegativeJsonDecimal | None
    ingredients: tuple[RecipePresentationIngredient, ...]
    steps: tuple[RecipePresentationStep, ...]

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def collections_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class RecipePresentationResolver(Protocol):
    async def resolve(self, candidate: RecipeProposalCandidate) -> RecipePresentation: ...


RecipeResolutionFailure = Literal["invalid_candidate", "resolver_unavailable", "resolver_contract_error"]


@dataclass(frozen=True)
class RecipeResolutionError(Exception):
    reason: RecipeResolutionFailure
    retryable: bool


class KochwikiRecipePresentationResolver:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._url = f"{base_url.rstrip('/')}/recipe-presentations/resolve"
        self._timeout_seconds = timeout_seconds

    async def resolve(self, candidate: RecipeProposalCandidate) -> RecipePresentation:
        return await asyncio.to_thread(self._resolve_sync, candidate)

    def _resolve_sync(self, candidate: RecipeProposalCandidate) -> RecipePresentation:
        try:
            body = RecipePresentationResolve(
                servings=candidate.servings,
                preptime=candidate.preparation_time,
                ingredients=[
                    RecipePresentationIngredientResolve(
                        index=ingredient.index,
                        amount=ingredient.amount,
                        foodstuffId=ingredient.foodstuff_reference,
                    )
                    for ingredient in candidate.ingredients
                ],
                steps=[
                    RecipePresentationStepResolve(index=step.index, description=step.description)
                    for step in candidate.steps
                ],
            ).model_dump_json().encode("utf-8")
        except (ValueError, TypeError, OverflowError) as error:
            raise RecipeResolutionError(reason="invalid_candidate", retryable=False) from error
        request = Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read()
        except HTTPError as error:
            raise RecipeResolutionError(
                reason="invalid_candidate" if error.code in (404, 422) else "resolver_unavailable",
                retryable=error.code not in (404, 422),
            ) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise RecipeResolutionError(reason="resolver_unavailable", retryable=True) from error
        try:
            wire = RecipePresentationOut.model_validate(json.loads(payload, parse_float=Decimal))
            return _map_presentation(wire)
        except (ValueError, TypeError, OverflowError) as error:
            raise RecipeResolutionError(reason="resolver_contract_error", retryable=False) from error


def _map_foodstuff(wire: FoodstuffSummaryOut) -> FoodstuffSummary:
    return FoodstuffSummary.model_validate(wire)


def _map_presentation(wire: RecipePresentationOut) -> RecipePresentation:
    return RecipePresentation(
        servings=wire.servings,
        preptime=wire.preptime,
        kcal=wire.kcal,
        carbs=wire.carbs,
        protein=wire.protein,
        fat=wire.fat,
        ingredients=tuple(
            RecipePresentationIngredient.model_validate(
                ingredient.model_dump() | {"foodstuff": _map_foodstuff(ingredient.foodstuff)}
            )
            for ingredient in wire.ingredients
        ),
        steps=tuple(
            RecipePresentationStep.model_validate(step.model_dump())
            for step in wire.steps
        ),
    )
