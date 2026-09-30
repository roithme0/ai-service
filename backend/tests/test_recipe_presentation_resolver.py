import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from types import TracebackType
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from kochwiki_contract import (
    FoodstuffSummaryOut, RecipePresentationIngredientOut, RecipePresentationOut,
    RecipePresentationStepOut, Unit,
)
from pydantic import ValidationError

from app.recipe_improvement.proposals import RecipeProposal, SourceProposalBase
from app.recipe_improvement.recipe import RecipeProposalCandidate
from app.recipe_improvement.resolver import (
    FoodstuffSummary, KochwikiRecipePresentationResolver, RecipePresentation,
    RecipePresentationIngredient, RecipePresentationStep, RecipeResolutionError,
)


def candidate(amount: str = "12.5", preptime: int | None = None) -> RecipeProposalCandidate:
    return RecipeProposalCandidate.model_validate({
        "name": "Oats", "servings": 2, "preparation_time": preptime,
        "ingredients": [{"index": 1, "amount": Decimal(amount), "foodstuff_reference": 7}],
        "steps": [{"index": 1, "description": "Mix."}],
    })


def presentation_body() -> dict[str, object]:
    return {
        "servings": 2, "preptime": None, "kcal": 120, "carbs": 10.25,
        "protein": 5, "fat": None,
        "ingredients": [{"index": 1, "amount": 12.5, "foodstuff": {
            "id": 7, "name": "Current oats", "brand": None, "unit": "G",
            "unitVerbose": "g", "kcal": 370, "carbs": 60.5, "protein": 13, "fat": None,
        }}],
        "steps": [{"index": 1, "description": "Mix."}],
    }


def object_at(body: dict[str, object], path: tuple[str | int, ...]) -> dict[str, object]:
    value: object = body
    for key in path:
        if isinstance(key, int):
            assert isinstance(value, list)
            value = value[key]
        else:
            assert isinstance(value, dict)
            value = value[key]
    assert isinstance(value, dict)
    return value


def test_snapshot_shapes_follow_shared_response_models() -> None:
    for snapshot, shared in (
        (FoodstuffSummary, FoodstuffSummaryOut),
        (RecipePresentationIngredient, RecipePresentationIngredientOut),
        (RecipePresentationStep, RecipePresentationStepOut),
    ):
        assert issubclass(snapshot, shared)
        assert snapshot.model_fields.keys() == shared.model_fields.keys()
    assert RecipePresentation.model_fields.keys() == RecipePresentationOut.model_fields.keys()


class Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "Response":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc_value: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def resolve_body(monkeypatch: pytest.MonkeyPatch, body: dict[str, object]) -> RecipePresentation:
    def respond(request: Request, timeout: float) -> Response:
        return Response(json.dumps(body).encode())

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    return asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))


@pytest.mark.parametrize("amount", ["12", "12.5"])
@pytest.mark.parametrize("preptime", [None, 15])
def test_serializes_shared_request_and_maps_authoritative_presentation(
    monkeypatch: pytest.MonkeyPatch, amount: str, preptime: int | None,
) -> None:
    requests: list[Request] = []

    def respond(request: Request, timeout: float) -> Response:
        requests.append(request)
        assert timeout == 3.5
        return Response(json.dumps(presentation_body()).encode())

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    resolved = asyncio.run(KochwikiRecipePresentationResolver(
        "http://kochwiki/api/", timeout_seconds=3.5,
    ).resolve(candidate(amount, preptime)))
    request = requests[0]
    assert request.data is not None
    body = json.loads(request.data)
    assert request.full_url == "http://kochwiki/api/recipe-presentations/resolve"
    assert request.method == "POST"
    assert dict(request.header_items()) == {
        "Content-type": "application/json", "Accept": "application/json",
    }
    assert body == {
        "servings": 2, "preptime": preptime,
        "ingredients": [{"index": 1, "amount": float(amount), "foodstuffId": 7}],
        "steps": [{"index": 1, "description": "Mix."}],
    }
    assert type(body["ingredients"][0]["amount"]) in (int, float)
    assert resolved.model_dump(mode="json") == presentation_body()
    assert type(resolved.ingredients[0].amount) is Decimal
    assert resolved.ingredients[0].foodstuff.unit is Unit.G
    assert type(resolved.kcal) is Decimal
    assert isinstance(resolved.ingredients, tuple)
    assert isinstance(resolved.steps, tuple)


@pytest.mark.parametrize("field", ["preptime", "kcal", "carbs", "protein", "fat"])
@pytest.mark.parametrize("value", [None, 15])
def test_response_nullable_fields_are_independent(
    monkeypatch: pytest.MonkeyPatch, field: str, value: int | None,
) -> None:
    body = presentation_body()
    body[field] = value
    assert resolve_body(monkeypatch, body).model_dump(mode="json") == body


@pytest.mark.parametrize("field", ["brand", "kcal", "carbs", "protein", "fat"])
@pytest.mark.parametrize("is_null", [True, False])
def test_foodstuff_nullable_fields_are_independent(
    monkeypatch: pytest.MonkeyPatch, field: str, is_null: bool,
) -> None:
    body = presentation_body()
    object_at(body, ("ingredients", 0, "foodstuff"))[field] = (
        None if is_null else ("Brand" if field == "brand" else 15.25)
    )
    assert resolve_body(monkeypatch, body).model_dump(mode="json") == body


@pytest.mark.parametrize("unit", ["G", "ML", "PIECE"])
def test_maps_all_unit_values(monkeypatch: pytest.MonkeyPatch, unit: str) -> None:
    body = presentation_body()
    object_at(body, ("ingredients", 0, "foodstuff"))["unit"] = unit
    resolved = resolve_body(monkeypatch, body)
    assert resolved.ingredients[0].foodstuff.unit is Unit(unit)
    assert resolved.model_dump(mode="json") == body


@pytest.mark.parametrize(("ingredients_empty", "steps_empty"), [(True, False), (False, True), (True, True)])
def test_accepts_empty_collections(
    monkeypatch: pytest.MonkeyPatch, ingredients_empty: bool, steps_empty: bool,
) -> None:
    body = presentation_body()
    if ingredients_empty:
        body["ingredients"] = []
    if steps_empty:
        body["steps"] = []
    assert resolve_body(monkeypatch, body).model_dump(mode="json") == body


@pytest.mark.parametrize("path", [(), ("ingredients", 0), ("ingredients", 0, "foodstuff"), ("steps", 0)])
def test_rejects_each_missing_or_undocumented_field(
    monkeypatch: pytest.MonkeyPatch, path: tuple[str | int, ...],
) -> None:
    for field in object_at(presentation_body(), path):
        body = presentation_body()
        del object_at(body, path)[field]
        with pytest.raises(RecipeResolutionError) as raised:
            resolve_body(monkeypatch, body)
        assert raised.value.retryable is False
        assert raised.value.reason == "resolver_contract_error"
        assert isinstance(raised.value.__cause__, ValidationError)
    body = presentation_body()
    object_at(body, path)["undocumented"] = None
    with pytest.raises(RecipeResolutionError) as raised:
        resolve_body(monkeypatch, body)
    assert raised.value.retryable is False
    assert raised.value.reason == "resolver_contract_error"


@pytest.mark.parametrize(("path", "field", "value"), [
    ((), "servings", "2"), ((), "servings", True), ((), "servings", 2.0),
    ((), "preptime", "15"), ((), "preptime", False),
    ((), "kcal", "120"), ((), "carbs", True), ((), "protein", []),
    ((), "ingredients", {}), ((), "steps", None),
    (("ingredients", 0), "amount", "12.5"), (("ingredients", 0), "amount", True),
    (("ingredients", 0), "index", "1"), (("ingredients", 0), "index", False),
    (("ingredients", 0), "foodstuff", []),
    (("ingredients", 0, "foodstuff"), "id", "7"),
    (("ingredients", 0, "foodstuff"), "id", True),
    (("ingredients", 0, "foodstuff"), "kcal", "370"),
    (("ingredients", 0, "foodstuff"), "fat", False),
    (("ingredients", 0, "foodstuff"), "unit", "KG"),
    (("ingredients", 0, "foodstuff"), "name", 42),
    (("steps", 0), "index", True), (("steps", 0), "description", 42),
    ((), "kcal", float("nan")), (("ingredients", 0), "amount", float("inf")),
])
def test_rejects_incorrect_wire_types(
    monkeypatch: pytest.MonkeyPatch, path: tuple[str | int, ...], field: str, value: object,
) -> None:
    body = presentation_body()
    object_at(body, path)[field] = value
    with pytest.raises(RecipeResolutionError) as raised:
        resolve_body(monkeypatch, body)
    assert raised.value.retryable is False
    assert raised.value.reason == "resolver_contract_error"
    assert isinstance(raised.value.__cause__, ValidationError)


@pytest.mark.parametrize(("path", "field", "value"), [
    ((), "servings", 100),
    ((), "preptime", 1000),
    (("ingredients", 0), "index", 100),
    (("ingredients", 0), "amount", 10000),
    (("steps", 0), "index", 100),
    ((), "kcal", 1000000.125), (("ingredients", 0, "foodstuff"), "carbs", 10000.5),
])
def test_snapshot_does_not_add_unjustified_output_bounds(
    monkeypatch: pytest.MonkeyPatch, path: tuple[str | int, ...], field: str, value: object,
) -> None:
    body = presentation_body()
    object_at(body, path)[field] = value
    RecipePresentationOut.model_validate_json(json.dumps(body))
    assert resolve_body(monkeypatch, body).model_dump(mode="json") == body


@pytest.mark.parametrize("path", [(), ("ingredients", 0), ("ingredients", 0, "foodstuff")])
@pytest.mark.parametrize("value", ["1e999", "1e-400"])
def test_shared_decimal_serialization_failures_are_controlled(
    monkeypatch: pytest.MonkeyPatch, path: tuple[str | int, ...], value: str,
) -> None:
    body = presentation_body()
    object_at(body, path)["amount" if path == ("ingredients", 0) else "kcal"] = Decimal(value)
    with pytest.raises(ValidationError):
        RecipePresentationOut.model_validate(body)

    def respond(request: Request, timeout: float) -> Response:
        payload = json.dumps(body, default=str).replace(json.dumps(str(Decimal(value))), value)
        return Response(payload.encode())

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    assert raised.value.retryable is False
    assert raised.value.reason == "resolver_contract_error"
    assert isinstance(raised.value.__cause__, ValidationError)


@pytest.mark.parametrize("value", ["0", "5e-324", "1.7976931348623157e308", "0.123456789012345678901234567"])
def test_shared_decimal_limits_and_rounding_survive_proposal_serialization(
    monkeypatch: pytest.MonkeyPatch, value: str,
) -> None:
    payload = json.dumps(presentation_body()).replace('"kcal": 120', '"kcal": ' + value).encode()

    def respond(request: Request, timeout: float) -> Response:
        return Response(payload)

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    resolved = asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    assert resolved.kcal == Decimal(value)
    proposal = RecipeProposal(
        proposal_id="proposal-1", created_at=datetime(2026, 9, 30, tzinfo=UTC),
        order=1, base=SourceProposalBase(), name="Oats", recipe=resolved, turn_id="turn-1",
    )
    assert proposal.recipe.kcal == Decimal(value)
    assert json.loads(proposal.model_dump_json())["recipe"]["kcal"] == float(value)


@pytest.mark.parametrize("field", ["servings", "preparation_time"])
def test_request_validation_failure_sends_nothing(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    invalid = candidate().model_copy(update={field: 0})

    def unexpected(request: Request, timeout: float) -> Response:
        pytest.fail("Invalid request must not be sent")

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", unexpected)
    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(invalid))
    assert raised.value.retryable is False
    assert raised.value.reason == "invalid_candidate"
    assert isinstance(raised.value.__cause__, ValidationError)


@pytest.mark.parametrize(("status", "retryable"), [
    (401, True), (404, False), (422, False), (429, True), (503, True),
])
def test_resolver_classifies_domain_and_transient_http_failures(
    monkeypatch: pytest.MonkeyPatch, status: int, retryable: bool,
) -> None:
    def fail(request: Request, timeout: float) -> Response:
        raise HTTPError("http://kochwiki", status, "failure", None, None)

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", fail)
    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    assert raised.value.retryable is retryable
    assert raised.value.reason == ("invalid_candidate" if status in (404, 422) else "resolver_unavailable")
    assert isinstance(raised.value.__cause__, HTTPError)


@pytest.mark.parametrize("failure", [URLError("offline"), TimeoutError(), OSError("connection reset")])
def test_transport_failures_are_retryable(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    def fail(request: Request, timeout: float) -> Response:
        raise failure

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", fail)
    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    assert raised.value.retryable is True
    assert raised.value.reason == "resolver_unavailable"
    assert raised.value.__cause__ is failure


@pytest.mark.parametrize("payload", [b"not json", b"\xff", b"null", b"[]"])
def test_malformed_success_bodies_are_controlled(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    def respond(request: Request, timeout: float) -> Response:
        return Response(payload)

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    with pytest.raises(RecipeResolutionError) as raised:
        asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    assert raised.value.retryable is False
    assert raised.value.reason == "resolver_contract_error"


def test_decimal_precision_survives_decode_mapping_and_arithmetic(monkeypatch: pytest.MonkeyPatch) -> None:
    precision = "0.123456789012345678901234567"
    payload = json.dumps(presentation_body()).replace('12.5', precision).replace('370', '0.1').encode()

    def respond(request: Request, timeout: float) -> Response:
        return Response(payload)

    monkeypatch.setattr("app.recipe_improvement.resolver.urlopen", respond)
    resolved = asyncio.run(KochwikiRecipePresentationResolver("http://kochwiki").resolve(candidate()))
    ingredient = resolved.ingredients[0]
    assert ingredient.amount == Decimal(precision)
    assert ingredient.foodstuff.kcal == Decimal("0.1")
    assert resolved.model_dump()["ingredients"][0]["amount"] == Decimal(precision)
    assert ingredient.foodstuff.kcal + Decimal("0.2") == Decimal("0.3")
    with localcontext() as context:
        context.prec = 50
        weighted = ingredient.amount * ingredient.foodstuff.kcal / Decimal("100")
        assert weighted == Decimal("0.000123456789012345678901234567")
        assert weighted * Decimal("1000") == ingredient.amount


def test_presentation_and_proposal_serialization_schemas_use_numbers_and_shared_units() -> None:
    schema = RecipeProposal.model_json_schema(mode="serialization")
    definitions = object_at(schema, ("$defs",))
    assert object_at(definitions, ("Unit",))["enum"] == ["G", "ML", "PIECE"]
    assert object_at(definitions, ("RecipePresentationIngredient", "properties", "amount")) == {
        "title": "Amount", "type": "number", "exclusiveMinimum": 0,
    }
    for name in ("RecipePresentation", "FoodstuffSummary"):
        for field in ("kcal", "carbs", "protein", "fat"):
            assert object_at(definitions, (name, "properties", field))["anyOf"] == [
                {"type": "number", "minimum": 0}, {"type": "null"},
            ]


@pytest.mark.parametrize("failure", [ValueError("mapping"), TypeError("mapping"), OverflowError("mapping")])
def test_mapping_failures_are_controlled_and_non_retryable(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    def fail(wire: RecipePresentationOut) -> RecipePresentation:
        raise failure

    monkeypatch.setattr("app.recipe_improvement.resolver._map_presentation", fail)
    with pytest.raises(RecipeResolutionError) as raised:
        resolve_body(monkeypatch, presentation_body())
    assert raised.value.retryable is False
    assert raised.value.reason == "resolver_contract_error"
    assert raised.value.__cause__ is failure


def test_resolved_proposal_is_deeply_immutable_and_preserves_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = presentation_body()
    resolved = resolve_body(monkeypatch, body)
    proposal = RecipeProposal(
        proposal_id="proposal-1", created_at=datetime(2026, 9, 30, tzinfo=UTC),
        order=1, base=SourceProposalBase(), name="Oats", recipe=resolved, turn_id="turn-1",
    )
    body["servings"] = 99
    object_at(body, ("ingredients", 0, "foodstuff"))["name"] = "Changed"
    with pytest.raises(ValidationError):
        resolved.servings = 99
    with pytest.raises(ValidationError):
        resolved.ingredients[0].amount = Decimal("42")
    with pytest.raises(ValidationError):
        resolved.ingredients[0].foodstuff.name = "Changed"
    with pytest.raises(ValidationError):
        resolved.steps[0].description = "Changed"
    with pytest.raises(ValidationError):
        proposal.name = "Changed"
    assert json.loads(proposal.model_dump_json()) == {
        "proposal_id": "proposal-1", "created_at": "2026-09-30T00:00:00Z", "order": 1,
        "base": {"kind": "source"}, "name": "Oats", "recipe": presentation_body(), "turn_id": "turn-1",
    }


@pytest.mark.parametrize(("path", "field", "value"), [
    ((), "servings", 0), ((), "preptime", 0), ((), "kcal", -1),
    (("ingredients", 0), "index", 0), (("ingredients", 0), "amount", 0),
    (("ingredients", 0, "foodstuff"), "id", 0),
    (("ingredients", 0, "foodstuff"), "carbs", -1),
    (("steps", 0), "index", 0), (("steps", 0), "description", ""),
    (("steps", 0), "description", "x" * 201),
])
def test_shared_response_invariants_fail_as_controlled_resolver_errors(
    monkeypatch: pytest.MonkeyPatch, path: tuple[str | int, ...], field: str, value: object,
) -> None:
    body = presentation_body()
    object_at(body, path)[field] = value
    with pytest.raises(RecipeResolutionError) as raised:
        resolve_body(monkeypatch, body)
    assert raised.value.reason == "resolver_contract_error"
    assert raised.value.retryable is False
    assert isinstance(raised.value.__cause__, ValidationError)
