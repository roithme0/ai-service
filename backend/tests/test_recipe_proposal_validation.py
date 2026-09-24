from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.recipe_improvement.validation import (
    RecipeProposalValidationFailure,
    RecipeProposalValidationSuccess,
    validate_recipe_proposal,
)


def valid_source() -> dict[str, object]:
    return {
        "external_reference": "source-recipe-42",
        "recipe": valid_recipe(ingredient_reference=1),
    }


def valid_recipe(ingredient_reference: int) -> dict[str, object]:
    return {
        "name": "Overnight oats",
        "servings": 2,
        "preparation_time": 15,
        "ingredients": [
            {"index": 4, "amount": Decimal("125.75"), "foodstuff_reference": ingredient_reference}
        ],
        "steps": [{"index": 3, "description": "Combine and chill."}],
    }


def test_accepts_complete_candidate_and_preserves_decimal_amount() -> None:
    candidate = valid_recipe(ingredient_reference=2)

    outcome = validate_recipe_proposal(
        valid_source(),
        {"foodstuff_references": [1, 2]},
        candidate,
    )

    assert isinstance(outcome, RecipeProposalValidationSuccess)
    expected = {**candidate, "ingredients": tuple(candidate["ingredients"]), "steps": tuple(candidate["steps"])}
    assert outcome.candidate.model_dump() == expected
    assert outcome.candidate.ingredients[0].amount == Decimal("125.75")
    assert isinstance(outcome.candidate.ingredients[0].amount, Decimal)


def test_rejects_origin_fields_on_candidate() -> None:
    candidate = valid_recipe(ingredient_reference=1)
    candidate["origin_url"] = "https://example.test"

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.issues[0].location == ("origin_url",)


def test_accepts_empty_ingredient_and_step_lists() -> None:
    candidate = valid_recipe(ingredient_reference=1)
    candidate["ingredients"] = []
    candidate["steps"] = []

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationSuccess)
    assert outcome.candidate.ingredients == ()
    assert outcome.candidate.steps == ()


def test_accepted_candidate_is_deeply_immutable_and_owned() -> None:
    candidate = valid_recipe(ingredient_reference=1)
    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationSuccess)
    candidate["name"] = "Changed"
    candidate["ingredients"][0]["foodstuff_reference"] = 2

    assert outcome.candidate.name == "Overnight oats"
    assert outcome.candidate.ingredients[0].foodstuff_reference == 1
    with pytest.raises(ValidationError):
        outcome.candidate.name = "Changed"
    with pytest.raises(ValidationError):
        outcome.candidate.ingredients[0].amount = Decimal("2")
    with pytest.raises(AttributeError):
        outcome.candidate.ingredients.append(outcome.candidate.ingredients[0])


def test_rejects_candidate_foodstuff_outside_availability_index() -> None:
    outcome = validate_recipe_proposal(
        valid_source(),
        {"foodstuff_references": [1]},
        valid_recipe(ingredient_reference=2),
    )

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "candidate"
    assert outcome.issues[0].location == ("ingredients", 0, "foodstuff_reference")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("servings", 0),
        ("preparation_time", 1000),
        ("origin_name", "x" * 201),
        ("origin_url", "relative/path"),
    ],
)
def test_rejects_invalid_candidate_recipe_fields(field: str, value: object) -> None:
    candidate = valid_recipe(ingredient_reference=1)
    candidate[field] = value

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "candidate"
    assert outcome.issues[0].location == (field,)


@pytest.mark.parametrize(
    "ingredients",
    [
        [
            {"index": 1, "amount": Decimal("1"), "foodstuff_reference": 1},
            {"index": 1, "amount": Decimal("2"), "foodstuff_reference": 2},
        ],
        [
            {"index": 1, "amount": Decimal("1"), "foodstuff_reference": 1},
            {"index": 2, "amount": Decimal("2"), "foodstuff_reference": 1},
        ],
    ],
)
def test_rejects_duplicate_ingredient_indexes_or_foodstuffs(ingredients: list[dict[str, object]]) -> None:
    candidate = valid_recipe(ingredient_reference=1)
    candidate["ingredients"] = ingredients

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1, 2]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "candidate"
    assert outcome.issues[0].location == ("ingredients",)


def test_rejects_duplicate_step_indexes_and_invalid_ingredient_amount() -> None:
    candidate = valid_recipe(ingredient_reference=1)
    candidate["steps"] = [
        {"index": 1, "description": "First."},
        {"index": 1, "description": "Second."},
    ]
    candidate["ingredients"] = [{"index": 1, "amount": Decimal("0"), "foodstuff_reference": 1}]

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "candidate"
    assert outcome.issues[0].location == ("ingredients", 0, "amount")


def test_rejects_invalid_source_and_index_before_candidate_evaluation() -> None:
    source = valid_source()
    source["recipe"] = valid_recipe(ingredient_reference=2)

    outcome = validate_recipe_proposal(
        source,
        {"foodstuff_references": [1, 1]},
        {"not": "a recipe"},
    )

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "input"
    assert outcome.issues[0].location == ("foodstuff_references",)


def test_rejects_structurally_invalid_source_before_candidate_evaluation() -> None:
    source_recipe = valid_recipe(ingredient_reference=1)
    source_recipe["name"] = ""
    source = {"external_reference": "source-recipe-42", "recipe": source_recipe}

    outcome = validate_recipe_proposal(
        source,
        {"foodstuff_references": [1]},
        {"not": "a recipe"},
    )

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "input"
    assert outcome.issues[0].location == ("recipe", "name")


@pytest.mark.parametrize("external_reference", [None, "", 42])
def test_rejects_invalid_source_external_reference(external_reference: object) -> None:
    source = valid_source()
    source["external_reference"] = external_reference

    outcome = validate_recipe_proposal(
        source,
        {"foodstuff_references": [1]},
        valid_recipe(ingredient_reference=1),
    )

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "input"
    assert outcome.issues[0].location == ("external_reference",)


def test_rejects_source_foodstuff_outside_availability_index_before_candidate() -> None:
    outcome = validate_recipe_proposal(
        valid_source(),
        {"foodstuff_references": [2]},
        {"not": "a recipe"},
    )

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "input"
    assert outcome.issues[0].location == ("recipe", "ingredients", 0, "foodstuff_reference")


def test_rejects_incomplete_candidate() -> None:
    candidate = valid_recipe(ingredient_reference=1)
    del candidate["steps"]

    outcome = validate_recipe_proposal(valid_source(), {"foodstuff_references": [1]}, candidate)

    assert isinstance(outcome, RecipeProposalValidationFailure)
    assert outcome.scope == "candidate"
    assert outcome.issues[0].location == ("steps",)
