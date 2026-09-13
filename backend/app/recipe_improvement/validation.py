"""Provider-neutral validation for complete recipe proposal candidates."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


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


class RecipeProposalCandidate(RecipeContent):
    pass


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    location: tuple[str | int, ...]
    message: str


class RecipeProposalValidationSuccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["success"] = "success"
    candidate: RecipeProposalCandidate


class RecipeProposalValidationFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["failure"] = "failure"
    scope: Literal["input", "candidate"]
    issues: tuple[ValidationIssue, ...]


RecipeProposalValidationOutcome = RecipeProposalValidationSuccess | RecipeProposalValidationFailure


def validate_recipe_proposal(
    source: object,
    availability_reference_index: object,
    candidate: object,
) -> RecipeProposalValidationOutcome:
    """Validate inputs before evaluating a complete proposal candidate."""
    try:
        validated_source = SourceRecipeSnapshot.model_validate(source)
    except ValidationError as error:
        return _input_failure(error)

    try:
        validated_index = AvailabilityReferenceIndex.model_validate(availability_reference_index)
    except ValidationError as error:
        return _input_failure(error)

    source_issues = unknown_foodstuff_issues(
        validated_source.recipe.ingredients,
        validated_index.foodstuff_references,
        ("recipe", "ingredients"),
    )
    if source_issues:
        return RecipeProposalValidationFailure(scope="input", issues=source_issues)

    try:
        validated_candidate = RecipeProposalCandidate.model_validate(candidate)
    except ValidationError as error:
        return RecipeProposalValidationFailure(scope="candidate", issues=_issues_from(error))

    candidate_issues = unknown_foodstuff_issues(
        validated_candidate.ingredients,
        validated_index.foodstuff_references,
        ("ingredients",),
    )
    if candidate_issues:
        return RecipeProposalValidationFailure(scope="candidate", issues=candidate_issues)

    return RecipeProposalValidationSuccess(candidate=validated_candidate)


def _input_failure(error: ValidationError) -> RecipeProposalValidationFailure:
    return RecipeProposalValidationFailure(scope="input", issues=_issues_from(error))


def _issues_from(error: ValidationError) -> tuple[ValidationIssue, ...]:
    return tuple(
        ValidationIssue(location=tuple(detail["loc"]), message=detail["msg"])
        for detail in error.errors()
    )


def unknown_foodstuff_issues(
    ingredients: Sequence[Ingredient],
    available_references: Sequence[int],
    location_prefix: tuple[str, ...],
) -> tuple[ValidationIssue, ...]:
    available_reference_set = set(available_references)
    return tuple(
        ValidationIssue(
            location=(*location_prefix, ingredient_position, "foodstuff_reference"),
            message="foodstuff reference is absent from the availability-reference index",
        )
        for ingredient_position, ingredient in enumerate(ingredients)
        if ingredient.foodstuff_reference not in available_reference_set
    )


def _validate_unique(values: Sequence[int], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
