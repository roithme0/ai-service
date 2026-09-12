"""Validated initialization input for recipe-improvement sessions."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.recipe_improvement.validation import (
    AvailabilityReferenceIndex,
    SourceRecipeSnapshot,
    ValidationIssue,
    unknown_foodstuff_issues,
)


class ImmutableIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int
    amount: Decimal
    foodstuff_reference: int


class ImmutablePreparationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    index: int
    description: str


class ImmutableRecipeContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str
    servings: int
    preparation_time: int | None
    origin_name: str | None
    origin_url: str | None
    ingredients: tuple[ImmutableIngredient, ...]
    steps: tuple[ImmutablePreparationStep, ...]

    @field_validator("ingredients", "steps", mode="before")
    @classmethod
    def convert_collections_to_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


class RecipeImprovementSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    external_reference: str
    recipe: ImmutableRecipeContent


class _RecipeImprovementSourceCandidate(SourceRecipeSnapshot):
    @field_validator("external_reference")
    @classmethod
    def validate_recipe_version_uuid(cls, value: str) -> str:
        try:
            UUID(value)
        except ValueError as error:
            raise ValueError("external_reference must be a valid recipe-version UUID") from error
        return value


class AvailableFoodstuffSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    external_reference: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    unit: Literal["G", "ML", "PIECE"]


class RecipeImprovementSessionInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: RecipeImprovementSourceSnapshot
    foodstuffs: tuple[AvailableFoodstuffSnapshot, ...]
    availability_reference_index: AvailabilityReferenceIndex


class RecipeImprovementSessionInputSuccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["success"] = "success"
    session_input: RecipeImprovementSessionInput


class RecipeImprovementSessionInputFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["failure"] = "failure"
    scope: Literal["input"] = "input"
    issues: tuple[ValidationIssue, ...]


RecipeImprovementSessionInputOutcome = (
    RecipeImprovementSessionInputSuccess | RecipeImprovementSessionInputFailure
)


def validate_recipe_improvement_session_input(
    source: object,
    foodstuffs: object,
) -> RecipeImprovementSessionInputOutcome:
    """Create an owned session snapshot from validated caller-provided data."""
    try:
        source_candidate = _RecipeImprovementSourceCandidate.model_validate(source)
    except ValidationError as error:
        return _input_failure(error, ("source",))

    try:
        validated_source = RecipeImprovementSourceSnapshot(
            external_reference=source_candidate.external_reference,
            recipe=ImmutableRecipeContent.model_validate(source_candidate.recipe.model_dump()),
        )
    except ValidationError as error:
        return _input_failure(error, ("source",))

    try:
        validated_foodstuffs = _FoodstuffSnapshotList.model_validate({"foodstuffs": foodstuffs})
    except ValidationError as error:
        return _input_failure(error)

    references = [foodstuff.external_reference for foodstuff in validated_foodstuffs.foodstuffs]
    index = AvailabilityReferenceIndex(foodstuff_references=references)
    source_issues = unknown_foodstuff_issues(
        source_candidate.recipe.ingredients,
        index.foodstuff_references,
        ("source", "recipe", "ingredients"),
    )
    if source_issues:
        return RecipeImprovementSessionInputFailure(issues=source_issues)

    return RecipeImprovementSessionInputSuccess(
        session_input=RecipeImprovementSessionInput(
            source=validated_source,
            foodstuffs=tuple(validated_foodstuffs.foodstuffs),
            availability_reference_index=index,
        )
    )


class _FoodstuffSnapshotList(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    foodstuffs: list[AvailableFoodstuffSnapshot] = Field(max_length=100)

    @field_validator("foodstuffs")
    @classmethod
    def validate_unique_references(
        cls, value: list[AvailableFoodstuffSnapshot]
    ) -> list[AvailableFoodstuffSnapshot]:
        references = [foodstuff.external_reference for foodstuff in value]
        if len(references) != len(set(references)):
            raise ValueError("foodstuff references must be unique")
        return value


def _input_failure(
    error: ValidationError, location_prefix: tuple[str, ...] = ()
) -> RecipeImprovementSessionInputFailure:
    return RecipeImprovementSessionInputFailure(
        issues=tuple(
            ValidationIssue(location=(*location_prefix, *detail["loc"]), message=detail["msg"])
            for detail in error.errors()
        )
    )
