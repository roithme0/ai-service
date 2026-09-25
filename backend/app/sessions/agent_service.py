"""Typed configured agent facade over the shared conversation store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.sessions.conversation import (
    ConversationMessageBusy, ConversationReadActive, ConversationSessionSettings,
    ConversationSessionStore, ConversationTurnResult,
)
from app.sessions.text_sessions import (
    TextSessionAppendOutcome, TextSessionCreation, TextSessionReadExpired,
    TextSessionReadUnknown,
)


InputT = TypeVar("InputT")
ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")
IssueT = TypeVar("IssueT")


@dataclass(frozen=True)
class AgentInputAccepted(Generic[ContextT]):
    context: ContextT


@dataclass(frozen=True)
class AgentInputRejected(Generic[IssueT]):
    issues: tuple[IssueT, ...]


class ConfiguredAgentService(Generic[InputT, ContextT, ArtifactT, IssueT]):
    def __init__(
        self,
        store: ConversationSessionStore[ContextT, ArtifactT],
        validate: Callable[[InputT], AgentInputAccepted[ContextT] | AgentInputRejected[IssueT]],
        execute: Callable[[str], Awaitable[ConversationTurnResult[ArtifactT]]],
        settings: ConversationSessionSettings,
    ) -> None:
        self._store = store
        self._validate = validate
        self._execute = execute
        self._settings = settings

    def create(self, session_input: InputT) -> TextSessionCreation | AgentInputRejected[IssueT]:
        validated = self._validate(session_input)
        if isinstance(validated, AgentInputRejected):
            return validated
        return self._store.create(validated.context, self._settings)

    def read(self, session_id: str) -> ConversationReadActive[ContextT, ArtifactT] | TextSessionReadExpired | TextSessionReadUnknown:
        return self._store.read(session_id)

    def append_user_message(self, session_id: str, text: str) -> TextSessionAppendOutcome | ConversationMessageBusy:
        return self._store.append_user_message(session_id, text)

    async def execute_turn(self, session_id: str) -> ConversationTurnResult[ArtifactT]:
        return await self._execute(session_id)
