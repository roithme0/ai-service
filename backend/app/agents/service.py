"""Typed configured agent facade over the shared conversation store."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from app.sessions.models.conversation import (
    ConversationMessageBusy,
    ConversationReadActive,
    ConversationSessionSettings,
    ConversationTurnReservation,
    ConversationTurnResult,
)
from app.sessions.conversation import ConversationSessionStore
from app.sessions.models.history import TerminalRecord
from app.sessions.observation import SessionObservation
from app.sessions.models.session import (
    TextSessionAppendOutcome,
    TextSessionCreation,
    TextSessionReadExpired,
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
        validate: Callable[
            [InputT], AgentInputAccepted[ContextT] | AgentInputRejected[IssueT]
        ],
        execute: Callable[
            [str, ConversationTurnReservation[ContextT, ArtifactT]],
            Awaitable[ConversationTurnResult[ArtifactT]],
        ],
        settings: ConversationSessionSettings,
    ) -> None:
        self._store = store
        self._validate = validate
        self._execute = execute
        self._settings = settings
        self._tasks: set[asyncio.Task[ConversationTurnResult[ArtifactT]]] = set()
        self._observation = SessionObservation(store)
        self._closed = False

    def create(
        self, session_input: InputT, owner: str
    ) -> TextSessionCreation | AgentInputRejected[IssueT]:
        validated = self._validate(session_input)
        if isinstance(validated, AgentInputRejected):
            return validated
        return self._store.create(validated.context, self._settings, owner)

    def belongs_to(self, session_id: str, owner: str) -> bool:
        return self._store.belongs_to(session_id, owner)

    def read(
        self, session_id: str
    ) -> (
        ConversationReadActive[ContextT, ArtifactT]
        | TextSessionReadExpired
        | TextSessionReadUnknown
    ):
        return self._store.read(session_id)

    def append_user_message(
        self, session_id: str, text: str
    ) -> TextSessionAppendOutcome | ConversationMessageBusy:
        return self._store.append_user_message(session_id, text)

    async def execute_turn(self, session_id: str) -> ConversationTurnResult[ArtifactT]:
        reservation = self._store.reserve_turn(session_id)
        if isinstance(reservation, ConversationTurnResult):
            return reservation
        return await self._execute(session_id, reservation)

    def start_turn(self, session_id: str) -> ConversationTurnResult[ArtifactT]:
        if self._closed:
            return ConversationTurnResult("unknown", "", None, ())
        reservation = self._store.admit_turn(session_id)
        if isinstance(reservation, ConversationTurnResult):
            return reservation

        async def run() -> ConversationTurnResult[ArtifactT]:
            try:
                return await self._execute(session_id, reservation)
            except asyncio.CancelledError:
                self._store.fail_turn(session_id, reservation)
                raise
            except Exception:
                return self._store.fail_turn(session_id, reservation)

        task = asyncio.create_task(run())
        self._tasks.add(task)

        def finished(
            completed: asyncio.Task[ConversationTurnResult[ArtifactT]],
        ) -> None:
            self._tasks.discard(completed)
            if completed.cancelled():
                self._store.fail_turn(session_id, reservation)

        task.add_done_callback(finished)
        return ConversationTurnResult("busy", reservation.turn_id, None, ())

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def turn_terminal(self, session_id: str, turn_id: str) -> TerminalRecord | None:
        return self._store.turn_terminal(session_id, turn_id)

    def observation_available(self, session_id: str) -> bool:
        return self._observation.observation_available(session_id)

    def observe(
        self, session_id: str
    ) -> AsyncIterator[
        ConversationReadActive[ContextT, ArtifactT]
        | TextSessionReadExpired
        | TextSessionReadUnknown
        | None
    ]:
        return self._observation.observe(session_id)
