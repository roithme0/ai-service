"""Bounded observation of session snapshots and lifecycle changes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Generic, TypeVar

from app.sessions.conversation import ConversationReadActive, ConversationSessionStore
from app.sessions.text_sessions import TextSessionReadExpired, TextSessionReadUnknown

ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")


class SessionObservation(Generic[ContextT, ArtifactT]):
    def __init__(self, store: ConversationSessionStore[ContextT, ArtifactT]) -> None:
        self._store = store
        self._observers: dict[str, int] = {}

    def observation_available(self, session_id: str) -> bool:
        return self._observers.get(session_id, 0) < 8

    async def observe(
        self, session_id: str
    ) -> AsyncIterator[
        ConversationReadActive[ContextT, ArtifactT]
        | TextSessionReadExpired
        | TextSessionReadUnknown
        | None
    ]:
        if not self.observation_available(session_id):
            yield None
            return
        self._observers[session_id] = self._observers.get(session_id, 0) + 1
        queue: asyncio.Queue[
            ConversationReadActive[ContextT, ArtifactT]
            | TextSessionReadExpired
            | TextSessionReadUnknown
        ] = asyncio.Queue(maxsize=128)
        overflow = False
        loop = asyncio.get_running_loop()

        def enqueue(
            value: (
                ConversationReadActive[ContextT, ArtifactT]
                | TextSessionReadExpired
                | TextSessionReadUnknown
            ),
        ) -> None:
            nonlocal overflow
            if queue.full():
                overflow = True
            elif not overflow:
                queue.put_nowait(value)

        def notify() -> None:
            value = self._store.read(session_id)
            try:
                same_loop = asyncio.get_running_loop() is loop
            except RuntimeError:
                same_loop = False
            if same_loop:
                enqueue(value)
            else:
                loop.call_soon_threadsafe(enqueue, value)

        detach = self._store.subscribe(session_id, notify)
        try:
            while True:
                if overflow:
                    yield None
                    return
                try:
                    value = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    value = self._store.read(session_id)
                yield value
                if not isinstance(value, ConversationReadActive):
                    return
        finally:
            detach()
            count = self._observers[session_id] - 1
            if count:
                self._observers[session_id] = count
            else:
                self._observers.pop(session_id, None)
