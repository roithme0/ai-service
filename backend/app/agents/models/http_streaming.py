"""Streamed events for the agent conversation HTTP API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from app.agents.models.http_responses import ArtifactResponse, SessionSnapshotResponse
from app.sessions.models.timeline import TimelineItem
from app.sessions.models.turns import TerminalTurnKind


StreamErrorReason = Literal["unavailable", "observation_limit"]


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
    reason: StreamErrorReason


StreamEventPayload = StreamSnapshot | StreamUpsert | StreamClosing | StreamTerminal | StreamError


class StreamEvent(RootModel[Annotated[StreamEventPayload, Field(discriminator="kind")]]):
    pass
