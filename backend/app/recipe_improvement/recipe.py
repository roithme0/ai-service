"""Recipe data types shared by session input and proposal validation."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int = Field(ge=1, le=99)
    amount: Decimal = Field(gt=0, le=9999)
    foodstuff_reference: int = Field(gt=0)


class PreparationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int = Field(ge=1, le=99)
    description: str = Field(min_length=1, max_length=200)


class RecipeContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(min_length=1, max_length=200)
    servings: int = Field(ge=1, le=99)
    preparation_time: int | None = Field(default=None, ge=1, le=999)
    origin_name: str | None = Field(default=None, max_length=200)
    origin_url: str | None = Field(default=None, max_length=200)
    ingredients: tuple[Ingredient, ...]
    steps: tuple[PreparationStep, ...]

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def convert_collections_to_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("origin_url", mode="before")
    @classmethod
    def normalize_empty_origin_url(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("origin_url")
    @classmethod
    def validate_origin_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("origin_url must be a valid absolute URL")
        return value

    @field_validator("ingredients")
    @classmethod
    def validate_unique_ingredients(cls, value: tuple[Ingredient, ...]) -> tuple[Ingredient, ...]:
        _validate_unique([ingredient.index for ingredient in value], "ingredient indexes")
        _validate_unique(
            [ingredient.foodstuff_reference for ingredient in value],
            "ingredient foodstuff references",
        )
        return value

    @field_validator("steps")
    @classmethod
    def validate_unique_step_indexes(
        cls, value: tuple[PreparationStep, ...]
    ) -> tuple[PreparationStep, ...]:
        _validate_unique([step.index for step in value], "step indexes")
        return value


class SourceRecipeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    external_reference: str = Field(min_length=1)
    recipe: RecipeContent


class AvailabilityReferenceIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    foodstuff_references: tuple[int, ...] = Field(default_factory=tuple)

    @field_validator("foodstuff_references", mode="before")
    @classmethod
    def convert_references_to_tuple(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("foodstuff_references")
    @classmethod
    def validate_unique_positive_references(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(reference <= 0 for reference in value):
            raise ValueError("foodstuff references must be positive")
        _validate_unique(value, "foodstuff references")
        return value


class RecipeProposalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(min_length=1, max_length=200)
    servings: int = Field(ge=1, le=99)
    preparation_time: int | None = Field(ge=1, le=999)
    ingredients: tuple[Ingredient, ...]
    steps: tuple[PreparationStep, ...]

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def convert_candidate_collections_to_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("ingredients")
    @classmethod
    def validate_unique_candidate_ingredients(
        cls, value: tuple[Ingredient, ...]
    ) -> tuple[Ingredient, ...]:
        _validate_unique([ingredient.index for ingredient in value], "ingredient indexes")
        _validate_unique(
            [ingredient.foodstuff_reference for ingredient in value],
            "ingredient foodstuff references",
        )
        return value

    @field_validator("steps")
    @classmethod
    def validate_unique_candidate_step_indexes(
        cls, value: tuple[PreparationStep, ...]
    ) -> tuple[PreparationStep, ...]:
        _validate_unique([step.index for step in value], "step indexes")
        return value


def _validate_unique(values: Sequence[int], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
