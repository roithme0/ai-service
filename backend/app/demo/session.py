"""Typed context and artifact payloads for demo conversations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from app.sessions.conversation import ConversationSessionSettings, ConversationSessionStore
from app.sessions.text_sessions import TextSessionCreation


SESSION_LIFETIME = timedelta(minutes=90)
MAX_ARTIFACTS = 1


@dataclass(frozen=True)
class DemoContext:
    kind: Literal["demo"] = "demo"


class GreetingPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: str


class DemoArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["demo.greeting"] = "demo.greeting"
    payload: GreetingPayload


DemoSessionStore: TypeAlias = ConversationSessionStore[DemoContext, DemoArtifact]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def new_demo_session_store(clock: Callable[[], datetime] = _utc_now) -> DemoSessionStore:
    return ConversationSessionStore(lifetime=SESSION_LIFETIME, clock=clock)


def create_demo_session(store: DemoSessionStore) -> TextSessionCreation:
    return store.create(DemoContext(), ConversationSessionSettings(max_artifacts=MAX_ARTIFACTS))
