"""Provider-neutral validation for complete recipe proposal candidates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.recipe_improvement.recipe import (
    AvailabilityReferenceIndex,
    Ingredient,
    RecipeProposalCandidate,
    SourceRecipeSnapshot,
)


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

