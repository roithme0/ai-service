"""Application-wide HTTP error and validation contracts."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

HttpErrorKind = Literal["not_found", "method_not_allowed", "http_error", "internal_error"]
RequestValidationErrorKind = Literal["request_validation"]
KindT = TypeVar("KindT", bound=str)


class ErrorEnvelope(BaseModel, Generic[KindT]):
    model_config = ConfigDict(extra="forbid", strict=True)
    detail: str = Field(min_length=1)
    kind: KindT


class HttpErrorResponse(ErrorEnvelope[HttpErrorKind]):
    pass


class ValidationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    loc: tuple[str | int, ...] = Field(min_length=1)
    msg: str = Field(min_length=1)
    type: str = Field(min_length=1)


class ValidationErrorEnvelope(BaseModel, Generic[KindT]):
    model_config = ConfigDict(extra="forbid", strict=True)
    detail: list[ValidationDetail] = Field(min_length=1)
    kind: KindT


class RequestValidationErrorResponse(ValidationErrorEnvelope[RequestValidationErrorKind]):
    pass
