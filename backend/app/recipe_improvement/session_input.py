"""Validated initialization input for recipe-improvement sessions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.recipe import (
    AvailabilityReferenceIndex,
    RecipeContent,
    SourceRecipeSnapshot,
)
from app.recipe_improvement.validation import ValidationIssue, unknown_foodstuff_issues

MAX_INITIAL_SNAPSHOT_CONTEXT_LENGTH = 16_000


class RecipeImprovementSourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    external_reference: str
    recipe: RecipeContent


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
    brand: str | None = Field(max_length=100)
    unit: Literal["G", "ML", "PIECE"]
    unit_verbose: str = Field(min_length=1, max_length=20)
    kcal: Decimal | None
    carbs: Decimal | None
    protein: Decimal | None
    fat: Decimal | None

    @field_validator("kcal", "carbs", "protein", "fat", mode="before")
    @classmethod
    def convert_nutrition_to_decimal(cls, value: object) -> object:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float, str)) and not isinstance(value, bool):
            try:
                converted = Decimal(str(value))
            except InvalidOperation:
                return value
            return converted if converted.is_finite() else value
        return value


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
            recipe=source_candidate.recipe,
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

    session_input = RecipeImprovementSessionInput(
        source=validated_source,
        foodstuffs=tuple(validated_foodstuffs.foodstuffs),
        availability_reference_index=index,
    )
    initial_snapshot_context = recipe_context(session_input)
    if len(initial_snapshot_context) > MAX_INITIAL_SNAPSHOT_CONTEXT_LENGTH:
        return RecipeImprovementSessionInputFailure(
            issues=(ValidationIssue(
                location=(),
                message=("initial source recipe and foodstuffs context exceeds "
                         f"{MAX_INITIAL_SNAPSHOT_CONTEXT_LENGTH} characters"),
            ),)
        )
    return RecipeImprovementSessionInputSuccess(session_input=session_input)


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
