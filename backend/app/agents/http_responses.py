"""HTTP response conversion for agent conversations."""

from typing import TypeVar

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.core.models import ValidationDetail
from app.sessions.models.artifacts import PublishedArtifact
from app.sessions.models.conversation import ConversationSnapshot
from app.agents.models.http_responses import (
    ErrorResponse,
    InputIssue,
    InputValidationErrorKind,
    SessionErrorKind,
    SessionSnapshotResponse,
    UserMessageResponse,
    ValidationErrorKind,
    ValidationErrorResponse,
)
from app.sessions.models.session import TextMessage
from app.sessions.models.timeline import TimelineArtifact, TimelineItem
from app.sessions.models.turns import TurnSnapshot

ContextT = TypeVar("ContextT")
PayloadT = TypeVar("PayloadT", bound=BaseModel)


def snapshot_response(
    snapshot: ConversationSnapshot[ContextT, PayloadT],
) -> SessionSnapshotResponse:
    return SessionSnapshotResponse(
        session_id=snapshot.session.session_id,
        expires_at=snapshot.session.expires_at,
        turns=[TurnSnapshot(
            turn_id=turn.turn_id, user_message_id=turn.user_message_id, status=turn.status,
            timeline=tuple(timeline_item_response(item) for item in turn.timeline),
        ) for turn in snapshot.turns],
        sequence=snapshot.sequence,
    )


def user_message_response(value: TextMessage) -> UserMessageResponse:
    return UserMessageResponse.model_validate(
        {"role": value.role, "text": value.text, "turn_id": value.turn_id}
    )


def timeline_item_response(item: TimelineItem[PayloadT]) -> TimelineItem[dict[str, object]]:
    if item.kind == "artifact":
        return TimelineArtifact(turn_id=item.turn_id, artifact=artifact_response(item.artifact))
    return item


def artifact_response(value: PublishedArtifact[PayloadT]) -> PublishedArtifact[dict[str, object]]:
    return PublishedArtifact(
        artifact_id=value.artifact_id,
        type=value.type,
        created_at=value.created_at,
        order=value.order,
        turn_id=value.turn_id,
        payload=value.payload.model_dump(mode="json"),
    )


def model_validation_details(error: ValidationError) -> list[ValidationDetail]:
    return [
        ValidationDetail(
            loc=("body", *issue["loc"]),
            msg=(
                "request must be an object"
                if issue["type"] == "model_type"
                else (
                    "extra field not permitted"
                    if issue["type"] == "extra_forbidden"
                    else issue["msg"]
                )
            ),
            type=issue["type"],
        )
        for issue in error.errors()
    ]


def validation_error_response(
    kind: ValidationErrorKind,
    detail: list[ValidationDetail],
) -> JSONResponse:
    return _json(422, ValidationErrorResponse(detail=detail, kind=kind))


def input_error_response(
    issues: tuple[InputIssue, ...],
    kind: InputValidationErrorKind = "invalid_input",
) -> JSONResponse:
    return validation_error_response(
        kind,
        [
            ValidationDetail(
                loc=("body", *issue.location), msg=issue.message, type="value_error"
            )
            for issue in issues
        ],
    )


def session_error_response(kind: SessionErrorKind, turn_id: str | None = None) -> JSONResponse:
    responses: dict[SessionErrorKind, tuple[int, str]] = {
        "unknown_configuration": (404, "Agent configuration not found"),
        "agent_unavailable": (503, "Agent unavailable"),
        "unknown": (404, "Session not found"),
        "expired": (410, "Session expired"),
        "busy": (409, "Session is busy"),
        "not_ready": (409, "Session is not ready for a turn"),
        "conflict": (409, "Session state changed during the turn"),
        "limit_reached": (409, "Session limit reached"),
        "generation_failed": (502, "Turn generation failed"),
    }
    status, detail = responses[kind]
    return _json(
        status, ErrorResponse(detail=detail, kind=kind, turn_id=turn_id or None)
    )


def _json(
    status: int, content: ErrorResponse | ValidationErrorResponse
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content=content.model_dump(mode="json", exclude_none=True)
    )
