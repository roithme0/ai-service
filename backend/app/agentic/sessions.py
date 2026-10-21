"""Internal owner-scoped session storage for the native agent runner."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import (
    DEFAULT_SESSION_LIFETIME,
    MAX_ARTIFACTS,
    MAX_OBSERVERS_PER_SESSION,
    MAX_PENDING_OBSERVATION_UPDATES,
)
from app.agentic.conversations import (
    AgentConversation,
    ConversationArtifact,
    ConversationTurn,
    latest_settled_observation,
)
from app.agentic.observation import TurnObservation
from app.agentic.artifact_models import ArtifactCapability


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionNotFoundError(LookupError):
    """The session is unknown, expired, or belongs to another owner."""


class ObservationLimitError(RuntimeError):
    """The session already has the maximum number of observers."""


class ObservationOverflowError(RuntimeError):
    """The observer fell behind; its stream cannot provide complete updates."""


@dataclass(frozen=True)
class SessionCreated:
    session_id: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionSnapshot:
    """Detached internal data; not a public timeline or HTTP contract."""

    session_id: str
    expires_at: datetime
    artifacts: tuple[ConversationArtifact, ...]
    turns: tuple[ConversationTurn, ...]
    initial_context_message: ModelRequest | None

    @property
    def last_turn(self) -> TurnObservation | None:
        return latest_settled_observation(self.turns)

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        observation = self.last_turn
        if observation is not None:
            return tuple(observation.messages)
        if self.initial_context_message is not None:
            return (self.initial_context_message,)
        return ()


@dataclass(frozen=True)
class _Session:
    owner: str
    expires_at: datetime
    conversation: AgentConversation


@dataclass(eq=False)
class _Observer:
    queue: asyncio.Queue[SessionSnapshot | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_PENDING_OBSERVATION_UPDATES),
    )
    overflow: bool = False


class AgentSessionRegistry:
    """In-process lifecycle only; callers own the shared agent's context lifetime.

    Use from one event loop. Never expose retained conversations to callers:
    each read and turn admission must pass ownership and expiry checks.
    """

    def __init__(
        self,
        *,
        lifetime: timedelta = DEFAULT_SESSION_LIFETIME,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if lifetime <= timedelta():
            raise ValueError("Session lifetime must be positive.")
        self._lifetime = lifetime
        self._clock = clock if clock is not None else _utc_now
        self._sessions: dict[str, _Session] = {}
        self._observers: dict[str, set[_Observer]] = {}
        self._observation_closed = False

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("Session clock must return timezone-aware timestamps.")
        return now.astimezone(UTC)

    def _discard_expired(self, now: datetime) -> None:
        for session_id in tuple(self._sessions):
            if now >= self._sessions[session_id].expires_at:
                del self._sessions[session_id]

    def create(
        self,
        *,
        owner: str,
        initial_context: dict[str, JsonValue] | None = None,
        artifact_capabilities: Sequence[ArtifactCapability] = (),
        max_artifacts: int = MAX_ARTIFACTS,
    ) -> SessionCreated:
        if not owner.strip():
            raise ValueError("Session owner must not be blank.")
        now = self._now()
        self._discard_expired(now)
        session_id = str(uuid4())
        conversation = AgentConversation(
            initial_context=initial_context,
            artifact_capabilities=artifact_capabilities,
            max_artifacts=max_artifacts,
            on_change=lambda: self._publish(session_id),
        )
        expires_at = now + self._lifetime
        self._sessions[session_id] = _Session(owner, expires_at, conversation)
        return SessionCreated(session_id, expires_at)

    def _find(self, session_id: str, owner: str) -> _Session:
        self._discard_expired(self._now())
        session = self._sessions.get(session_id)
        if session is None or session.owner != owner:
            raise SessionNotFoundError("Session not found.")
        return session

    def read(self, session_id: str, *, owner: str) -> SessionSnapshot:
        session = self._find(session_id, owner)
        return self._snapshot(session_id, session)

    @staticmethod
    def _snapshot(session_id: str, session: _Session) -> SessionSnapshot:
        conversation = session.conversation
        return SessionSnapshot(
            session_id=session_id,
            expires_at=session.expires_at,
            artifacts=conversation.artifacts,
            turns=conversation.turns,
            initial_context_message=conversation.initial_context_message,
        )

    def _publish(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        for observer in self._observers.get(session_id, ()):
            if observer.overflow:
                continue
            if observer.queue.full():
                observer.overflow = True
            else:
                observer.queue.put_nowait(self._snapshot(session_id, session))

    def close_observers(self) -> None:
        self._observation_closed = True
        for observers in self._observers.values():
            for observer in observers:
                if not observer.queue.full():
                    observer.queue.put_nowait(None)

    async def observe(self, session_id: str, *, owner: str) -> AsyncGenerator[SessionSnapshot, None]:
        """Yield detached boundary snapshots; disconnect never controls execution."""
        session = self._find(session_id, owner)
        observers = self._observers.setdefault(session_id, set())
        if len(observers) >= MAX_OBSERVERS_PER_SESSION:
            raise ObservationLimitError("Session observer limit reached.")
        observer = _Observer()
        observers.add(observer)
        try:
            yield self._snapshot(session_id, session)
            while True:
                self._find(session_id, owner)
                if observer.overflow:
                    raise ObservationOverflowError("Session observation fell behind.")
                if self._observation_closed and observer.queue.empty():
                    return
                timeout = (session.expires_at - self._now()).total_seconds()
                try:
                    snapshot = await asyncio.wait_for(observer.queue.get(), timeout=max(0.0, timeout))
                except TimeoutError:
                    continue
                self._find(session_id, owner)
                if observer.overflow:
                    raise ObservationOverflowError("Session observation fell behind.")
                if snapshot is None:
                    return
                yield snapshot
        finally:
            observers.remove(observer)
            if not observers:
                self._observers.pop(session_id, None)

    async def execute_turn(
        self,
        session_id: str,
        *,
        owner: str,
        agent: Agent[None, str],
        prompt: str,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
        on_admitted: Callable[[], None] | None = None,
    ) -> AgentRunResult[str]:
        """Check access, then await the conversation through settlement."""
        session = self._find(session_id, owner)
        return await session.conversation.execute_turn(
            agent,
            prompt,
            usage_limits=usage_limits,
            toolsets=toolsets,
            on_admitted=on_admitted,
        )

