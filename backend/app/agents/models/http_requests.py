"""Requests for the agent conversation HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SessionCreationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    input: object = None


class UserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class EmptyTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
