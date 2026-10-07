"""Visible conversation timeline contracts."""

from dataclasses import dataclass
from typing import Literal

from app.sessions.models.session import SessionRole


TimelineToolStatus = Literal["requested", "running", "completed", "failed", "not_executed", "outcome_unknown"]


@dataclass(frozen=True)
class TimelineMessage:
    turn_id: str
    id: str
    role: SessionRole
    text: str
    kind: Literal["message"]


@dataclass(frozen=True)
class TimelineIntermediateMessage:
    turn_id: str
    id: str
    text: str
    kind: Literal["intermediate"]


@dataclass(frozen=True)
class TimelineTool:
    turn_id: str
    execution_id: str
    name: str
    status: TimelineToolStatus
    kind: Literal["tool"]


@dataclass(frozen=True)
class TimelineArtifact:
    turn_id: str
    artifact_id: str
    kind: Literal["artifact"]


@dataclass(frozen=True)
class TimelineFailure:
    turn_id: str
    kind: Literal["failure"]


type TimelineItem = TimelineMessage | TimelineIntermediateMessage | TimelineTool | TimelineArtifact | TimelineFailure

