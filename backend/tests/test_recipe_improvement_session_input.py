from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.recipe_improvement.session_input import (
    RecipeImprovementSessionInputFailure,
    RecipeImprovementSessionInputSuccess,
    validate_recipe_improvement_session_input,
)
from app.recipe_improvement.validation import RecipeProposalValidationSuccess, validate_recipe_proposal


RECIPE_VERSION_UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def valid_source(foodstuff_reference: int = 1) -> dict[str, object]:
    return {
        "external_reference": RECIPE_VERSION_UUID,
        "recipe": {
            "name": "Overnight oats",
            "servings": 2,
            "preparation_time": 15,
            "origin_name": "Kitchen",
            "origin_url": "https://example.test/overnight-oats",
            "ingredients": [
                {"index": 4, "amount": Decimal("125.75"), "foodstuff_reference": foodstuff_reference}
            ],
            "steps": [{"index": 3, "description": "Combine and chill."}],
        },
    }


def valid_foodstuff(reference: int = 1) -> dict[str, object]:
    return {"external_reference": reference, "name": "Oats", "brand": "Pantry", "unit": "G",
            "unit_verbose": "g", "kcal": Decimal("370"), "carbs": Decimal("60"),
            "protein": Decimal("13"), "fat": Decimal("7")}


def test_accepts_source_and_unique_foodstuffs_with_derived_index() -> None:
    outcome = validate_recipe_improvement_session_input(
        valid_source(), [valid_foodstuff(1), {**valid_foodstuff(2), "unit": "ML"}]
    )

    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)
    assert outcome.session_input.availability_reference_index.foodstuff_references == (1, 2)
    assert outcome.session_input.foodstuffs[1].unit == "ML"


@pytest.mark.parametrize(
    ("source", "foodstuffs", "location"),
    [
        ({**valid_source(), "external_reference": "not-a-uuid"}, [valid_foodstuff()], ("source", "external_reference")),
        (valid_source(), [{**valid_foodstuff(), "name": ""}], ("foodstuffs", 0, "name")),
        (valid_source(), [{key: value for key, value in valid_foodstuff().items() if key != "brand"}], ("foodstuffs", 0, "brand")),
        (valid_source(), [{key: value for key, value in valid_foodstuff().items() if key != "kcal"}], ("foodstuffs", 0, "kcal")),
        (valid_source(), [{**valid_foodstuff(), "brand": "x" * 101}], ("foodstuffs", 0, "brand")),
        (valid_source(), [{**valid_foodstuff(), "unit": "GRAM"}], ("foodstuffs", 0, "unit")),
        (valid_source(), [valid_foodstuff(), valid_foodstuff()], ("foodstuffs",)),
        (valid_source(2), [valid_foodstuff(1)], ("source", "recipe", "ingredients", 0, "foodstuff_reference")),
    ],
)
def test_rejects_invalid_session_input(
    source: dict[str, object], foodstuffs: list[dict[str, object]], location: tuple[str | int, ...]
) -> None:
    outcome = validate_recipe_improvement_session_input(source, foodstuffs)

    assert isinstance(outcome, RecipeImprovementSessionInputFailure)
    assert outcome.issues[0].location == location


def test_rejects_more_than_one_hundred_foodstuffs() -> None:
    outcome = validate_recipe_improvement_session_input(
        valid_source(), [valid_foodstuff(reference) for reference in range(1, 102)]
    )

    assert isinstance(outcome, RecipeImprovementSessionInputFailure)
    assert outcome.issues[0].location == ("foodstuffs",)


def test_session_input_reuses_recipe_content_validation() -> None:
    source = valid_source()
    source["recipe"] = {**source["recipe"], "servings": 0}

    outcome = validate_recipe_improvement_session_input(source, [valid_foodstuff()])

    assert isinstance(outcome, RecipeImprovementSessionInputFailure)
    assert outcome.issues[0].location == ("source", "recipe", "servings")


def test_accepts_empty_snapshot_only_for_source_without_ingredients() -> None:
    source = valid_source()
    source["recipe"] = {**source["recipe"], "ingredients": []}

    outcome = validate_recipe_improvement_session_input(source, [])

    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)
    assert outcome.session_input.availability_reference_index.foodstuff_references == ()


def test_accepted_snapshot_is_independent_from_caller_mutations() -> None:
    source = valid_source()
    foodstuffs = [valid_foodstuff()]

    outcome = validate_recipe_improvement_session_input(source, foodstuffs)
    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)

    source["recipe"]["name"] = "Changed"
    source["recipe"]["ingredients"][0]["foodstuff_reference"] = 2
    foodstuffs[0]["name"] = "Changed"
    foodstuffs.append(valid_foodstuff(2))

    assert outcome.session_input.source.recipe.name == "Overnight oats"
    assert outcome.session_input.source.recipe.ingredients[0].foodstuff_reference == 1
    assert outcome.session_input.foodstuffs[0].name == "Oats"
    assert outcome.session_input.availability_reference_index.foodstuff_references == (1,)


def test_accepted_session_input_cannot_be_mutated_through_nested_objects() -> None:
    outcome = validate_recipe_improvement_session_input(valid_source(), [valid_foodstuff()])
    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)

    with pytest.raises(ValidationError):
        outcome.session_input.source.recipe.name = "Changed"
    with pytest.raises(ValidationError):
        outcome.session_input.source.recipe.ingredients[0].amount = Decimal("2")
    with pytest.raises(AttributeError):
        outcome.session_input.source.recipe.ingredients.append(
            outcome.session_input.source.recipe.ingredients[0]
        )
    with pytest.raises(AttributeError):
        outcome.session_input.availability_reference_index.foodstuff_references.append(2)


def test_accepted_input_remains_compatible_with_proposal_validation() -> None:
    outcome = validate_recipe_improvement_session_input(valid_source(), [valid_foodstuff()])
    assert isinstance(outcome, RecipeImprovementSessionInputSuccess)

    proposal_outcome = validate_recipe_proposal(
        outcome.session_input.source.model_dump(),
        outcome.session_input.availability_reference_index,
        {key: value for key, value in valid_source()["recipe"].items()
         if key not in ("origin_name", "origin_url")},
    )

    assert isinstance(proposal_outcome, RecipeProposalValidationSuccess)
