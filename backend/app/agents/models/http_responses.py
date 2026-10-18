"""Responses and errors for the agent conversation HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.models import (
    ErrorEnvelope, HttpErrorKind, RequestValidationErrorKind, ValidationErrorEnvelope,
)
from app.sessions.models.turns import TurnSnapshot


class InputIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    location: tuple[str | int, ...]
    message: str


SessionErrorKind = Literal[
    "unknown_configuration",
    "agent_unavailable",
    "unknown",
    "expired",
    "busy",
    "not_ready",
    "conflict",
    "limit_reached",
    "generation_failed",
]

ErrorKind = Literal[HttpErrorKind, SessionErrorKind]
InputValidationErrorKind = Literal["invalid_input", "invalid_message"]
ValidationErrorKind = Literal[InputValidationErrorKind, RequestValidationErrorKind]


class ErrorResponse(ErrorEnvelope[ErrorKind]):
    turn_id: str | None = None


class ValidationErrorResponse(ValidationErrorEnvelope[ValidationErrorKind]):
    pass


class UserMessageResponse(BaseModel):
    role: Literal["user"]
    text: str
    turn_id: str


class SessionCreationResponse(BaseModel):
    session_id: str
    expires_at: datetime

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return value.isoformat()


class SessionSnapshotResponse(BaseModel):
    session_id: str
    expires_at: datetime
    turns: list[TurnSnapshot[dict[str, object]]]
    sequence: int = Field(ge=0)

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return value.isoformat()


class AcceptedTurnResponse(BaseModel):
    kind: Literal["accepted"]
    turn_id: str
