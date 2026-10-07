"""Session HTTP requests, responses, and streamed event contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_serializer

from app.core.models import (
    ErrorEnvelope,
    HttpErrorKind,
    RequestValidationErrorKind,
    ValidationErrorEnvelope,
)
from app.sessions.models.timeline import TimelineItem
from app.sessions.models.turns import ActiveTurnStatus, TerminalTurnKind, TurnKind


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
ValidationErrorKind = Literal["invalid_input", "invalid_message", RequestValidationErrorKind]


class ErrorResponse(ErrorEnvelope[ErrorKind]):
    turn_id: str | None = None


class ValidationErrorResponse(ValidationErrorEnvelope[ValidationErrorKind]):
    pass


class SessionCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input: object = None


class UserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class EmptyTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UserMessageResponse(BaseModel):
    role: Literal["user"]
    text: str
    turn_id: None


class AssistantMessageResponse(BaseModel):
    role: Literal["assistant"]
    text: str
    turn_id: str


MessageResponse = Annotated[
    UserMessageResponse | AssistantMessageResponse, Field(discriminator="role")
]


class ArtifactResponse(BaseModel):
    artifact_id: str
    type: str
    created_at: datetime
    order: int
    turn_id: str
    payload: dict[str, object]

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.isoformat()


class SessionCreationResponse(BaseModel):
    session_id: str
    expires_at: datetime

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return value.isoformat()


class SessionSnapshotResponse(BaseModel):
    session_id: str
    expires_at: datetime
    messages: list[MessageResponse]
    artifacts: list[ArtifactResponse]
    terminal_turn_id: str | None
    terminal_turn_kind: TurnKind | None
    timeline: list[Annotated[TimelineItem, Field(discriminator="kind")]]
    active_turn_id: str | None
    active_turn_status: ActiveTurnStatus | None
    sequence: int = Field(ge=0)

    @field_serializer("expires_at")
    def serialize_expires_at(self, value: datetime) -> str:
        return value.isoformat()


class AcceptedTurnResponse(BaseModel):
    kind: Literal["accepted"]
    turn_id: str


class StreamSnapshot(BaseModel):
    kind: Literal["snapshot"]
    turn_id: str
    snapshot: SessionSnapshotResponse


class StreamUpsert(BaseModel):
    kind: Literal["upsert"]
    turn_id: str
    identity: str
    order: int = Field(ge=0)
    sequence: int = Field(ge=0)
    item: Annotated[TimelineItem, Field(discriminator="kind")]
    artifact: ArtifactResponse | None = None


class StreamClosing(BaseModel):
    kind: Literal["closing"]
    turn_id: str
    sequence: int = Field(ge=0)


class StreamTerminal(BaseModel):
    kind: Literal["terminal"]
    turn_id: str
    sequence: int = Field(ge=0)
    outcome: TerminalTurnKind


class StreamError(BaseModel):
    kind: Literal["error"]
    turn_id: str
    reason: Literal["unavailable", "observation_limit"]


class StreamEvent(
    RootModel[
        Annotated[
            StreamSnapshot
            | StreamUpsert
            | StreamClosing
            | StreamTerminal
            | StreamError,
            Field(discriminator="kind"),
        ]
    ]
):
    pass
