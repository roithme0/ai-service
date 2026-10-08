import pytest
from pydantic import ValidationError

from app.core.models import HttpErrorResponse, RequestValidationErrorResponse


def test_global_http_errors_reject_session_kinds_and_turn_identifiers() -> None:
    assert HttpErrorResponse(detail="Not Found", kind="not_found").model_dump() == {
        "detail": "Not Found", "kind": "not_found",
    }
    with pytest.raises(ValidationError):
        HttpErrorResponse.model_validate({"detail": "Expired", "kind": "expired"})
    with pytest.raises(ValidationError):
        HttpErrorResponse.model_validate({
            "detail": "Not Found", "kind": "not_found", "turn_id": "turn",
        })


def test_global_validation_errors_reject_session_validation_kinds() -> None:
    detail = [{"loc": ("body",), "msg": "Invalid", "type": "value_error"}]
    accepted = RequestValidationErrorResponse.model_validate({
        "kind": "request_validation", "detail": detail,
    })
    assert accepted.kind == "request_validation"
    with pytest.raises(ValidationError):
        RequestValidationErrorResponse.model_validate({
            "kind": "invalid_input", "detail": detail,
        })
