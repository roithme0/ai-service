"""Kochwiki recipe-presentation resolver boundary."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.recipe_improvement.recipe import RecipeProposalCandidate


class FoodstuffSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: int = Field(gt=0)
    name: str
    brand: str | None
    unit: Literal["G", "ML", "PIECE"]
    unitVerbose: str
    kcal: float | None
    carbs: float | None
    protein: float | None
    fat: float | None


class RecipePresentationIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int = Field(ge=1, le=99)
    amount: float = Field(gt=0, le=9999)
    foodstuff: FoodstuffSummary


class RecipePresentationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int = Field(ge=1, le=99)
    description: str = Field(min_length=1, max_length=200)


class RecipePresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    servings: int = Field(ge=1, le=99)
    preptime: int | None = Field(ge=1, le=999)
    kcal: float | None
    carbs: float | None
    protein: float | None
    fat: float | None
    ingredients: tuple[RecipePresentationIngredient, ...]
    steps: tuple[RecipePresentationStep, ...]

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def collections_to_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class RecipePresentationResolver(Protocol):
    async def resolve(self, candidate: RecipeProposalCandidate) -> RecipePresentation: ...


@dataclass(frozen=True)
class RecipeResolutionError(Exception):
    retryable: bool


class KochwikiRecipePresentationResolver:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._url = f"{base_url.rstrip('/')}/recipe-presentations/resolve"
        self._timeout_seconds = timeout_seconds

    async def resolve(self, candidate: RecipeProposalCandidate) -> RecipePresentation:
        return await asyncio.to_thread(self._resolve_sync, candidate)

    def _resolve_sync(self, candidate: RecipeProposalCandidate) -> RecipePresentation:
        body = {
            "servings": candidate.servings,
            "preptime": candidate.preparation_time,
            "ingredients": [
                {
                    "index": ingredient.index,
                    "amount": _json_number(ingredient.amount),
                    "foodstuffId": ingredient.foodstuff_reference,
                }
                for ingredient in candidate.ingredients
            ],
            "steps": [step.model_dump(mode="json") for step in candidate.steps],
        }
        request = Request(
            self._url,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except HTTPError as error:
            raise RecipeResolutionError(retryable=error.code not in (404, 422)) from error
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise RecipeResolutionError(retryable=True) from error
        try:
            return RecipePresentation.model_validate(payload)
        except ValidationError as error:
            raise RecipeResolutionError(retryable=True) from error


class UnavailableRecipePresentationResolver:
    async def resolve(self, candidate: RecipeProposalCandidate) -> RecipePresentation:
        raise RecipeResolutionError(retryable=True)


def _json_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    return int(integral) if value == integral else float(value)
