import asyncio
import json
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from app.recipe_improvement.recipe import RecipeProposalCandidate
from app.recipe_improvement.resolver import (
    KochwikiRecipePresentationResolver,
    RecipeResolutionError,
)


def candidate() -> RecipeProposalCandidate:
    return RecipeProposalCandidate.model_validate({
        "name": "Oats", "servings": 2, "preparation_time": None,
        "ingredients": [{"index": 1, "amount": Decimal("12.5"), "foodstuff_reference": 7}],
        "steps": [{"index": 1, "description": "Mix."}],
    })


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({
            "servings": 2, "preptime": None, "kcal": 120, "carbs": 10,
            "protein": 5, "fat": None,
            "ingredients": [{"index": 1, "amount": 12.5, "foodstuff": {
                "id": 7, "name": "Current oats", "brand": None, "unit": "G",
                "unitVerbose": "g", "kcal": 370, "carbs": 60, "protein": 13, "fat": None,
            }}],
            "steps": [{"index": 1, "description": "Mix."}],
        }).encode()


def test_resolver_maps_candidate_and_accepts_authoritative_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[object] = []

    def respond(request: object, timeout: float) -> Response:
        requests.append(request)
        assert timeout == 5.0
        return Response()

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)

    resolved = asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki/api").resolve(candidate()))

    request = requests[0]
    body = json.loads(request.data)
    assert request.full_url == "http://kochwiki/api/recipe-presentations/resolve"
    assert body == {
        "servings": 2, "preptime": None,
        "ingredients": [{"index": 1, "amount": 12.5, "foodstuffId": 7}],
        "steps": [{"index": 1, "description": "Mix."}],
    }
    assert resolved.ingredients[0].foodstuff.name == "Current oats"
    assert resolved.fat is None


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(401, True), (404, False), (422, False), (429, True), (503, True)],
)
def test_resolver_classifies_domain_and_transient_http_failures(
    monkeypatch: pytest.MonkeyPatch, status: int, retryable: bool
) -> None:
    def fail(request: object, timeout: float) -> Response:
        raise HTTPError("http://kochwiki", status, "failure", {}, None)

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", fail)

    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))

    assert raised.value.retryable is retryable
