"""Visible conversation timeline contracts."""

from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import ConfigDict

from app.sessions.models.session import SessionRole


TimelineToolStatus = Literal["requested", "running", "completed", "failed", "not_executed", "outcome_unknown"]


def _required_kind_schema(schema: dict[str, object]) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        kind = properties.get("kind")
        if isinstance(kind, dict):
            kind.pop("default", None)

@dataclass(frozen=True)
class TimelineMessage:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_required_kind_schema,
    )

    turn_id: str
    id: str
    role: SessionRole
    text: str
    kind: Literal["message"] = "message"


@dataclass(frozen=True)
class TimelineIntermediateMessage:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_required_kind_schema,
    )

    turn_id: str
    id: str
    text: str
    kind: Literal["intermediate"] = "intermediate"


@dataclass(frozen=True)
class TimelineTool:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_required_kind_schema,
    )

    turn_id: str
    execution_id: str
    name: str
    status: TimelineToolStatus
    kind: Literal["tool"] = "tool"


@dataclass(frozen=True)
class TimelineArtifact:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_required_kind_schema,
    )

    turn_id: str
    artifact_id: str
    kind: Literal["artifact"] = "artifact"


@dataclass(frozen=True)
class TimelineFailure:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        json_schema_serialization_defaults_required=True,
        json_schema_extra=_required_kind_schema,
    )

    turn_id: str
    kind: Literal["failure"] = "failure"


type TimelineItem = TimelineMessage | TimelineIntermediateMessage | TimelineTool | TimelineArtifact | TimelineFailure

