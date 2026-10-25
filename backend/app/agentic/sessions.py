"""Internal owner-scoped session storage for the native agent runner."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic_ai import Agent, Conversation
from pydantic_ai.messages import ModelMessage
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import (
    DEFAULT_SESSION_LIFETIME,
    MAX_ARTIFACTS_PER_SESSION,
    MAX_OBSERVERS_PER_SESSION,
    MAX_PENDING_OBSERVATION_UPDATES,
)
from app.agentic.session_state import (
    SessionState,
    SessionArtifact,
    TurnExecution,
)
from app.agentic.artifacts import ArtifactCapability
from app.agentic.identity import bind_turn_identity
from app.core.json import FiniteJsonValue
from app.core.identity import ApplicationIdentity


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
    artifacts: tuple[SessionArtifact, ...]
    turn_executions: tuple[TurnExecution, ...]
    conversation: Conversation
    limit_reached: bool

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        """Current native execution view, falling back to settled state during setup."""
        observation = self.turn_executions[-1].observation if self.turn_executions else None
        if observation is not None and observation.run_id is not None:
            return tuple(observation.messages)
        return tuple(self.conversation.messages)


@dataclass(frozen=True)
class _Session:
    owner: ApplicationIdentity
    expires_at: datetime
    state: SessionState


@dataclass(eq=False)
class _Observer:
    queue: asyncio.Queue[SessionSnapshot | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_PENDING_OBSERVATION_UPDATES),
    )
    overflow: bool = False

    def publish(self, snapshot_factory: Callable[[], SessionSnapshot]) -> None:
        if self.overflow:
            return
        if self.queue.full():
            self.overflow = True
        else:
            self.queue.put_nowait(snapshot_factory())

    def check_overflow(self) -> None:
        if self.overflow:
            raise ObservationOverflowError("Session observation fell behind.")

    def close(self) -> None:
        if not self.queue.full():
            self.queue.put_nowait(None)


class AgentSessionRegistry:
    """In-process lifecycle only; callers own the shared agent's context lifetime.

    Use from one event loop. Never expose retained session state to callers:
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
        self._observers_closed = False

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
        owner: ApplicationIdentity,
        initial_context: dict[str, FiniteJsonValue] | None = None,
        artifact_capabilities: Sequence[ArtifactCapability] = (),
        max_artifacts: int = MAX_ARTIFACTS_PER_SESSION,
    ) -> SessionCreated:
        now = self._now()
        self._discard_expired(now)
        session_id = str(uuid4())
        state = SessionState(
            initial_context=initial_context,
            artifact_capabilities=artifact_capabilities,
            max_artifacts=max_artifacts,
            on_change=lambda: self._publish(session_id),
        )
        expires_at = now + self._lifetime
        self._sessions[session_id] = _Session(owner=owner, expires_at=expires_at, state=state)
        return SessionCreated(session_id, expires_at)

    def _require_session(self, session_id: str, owner: ApplicationIdentity) -> _Session:
        self._discard_expired(self._now())
        session = self._sessions.get(session_id)
        if session is None or session.owner != owner:
            raise SessionNotFoundError("Session not found.")
        return session

    def read(self, session_id: str, *, owner: ApplicationIdentity) -> SessionSnapshot:
        session = self._require_session(session_id, owner)
        return self._create_snapshot(session_id, session)

    @staticmethod
    def _create_snapshot(session_id: str, session: _Session) -> SessionSnapshot:
        state = session.state
        return SessionSnapshot(
            session_id=session_id,
            expires_at=session.expires_at,
            artifacts=state.artifacts,
            turn_executions=state.turn_executions,
            conversation=state.conversation,
            limit_reached=state.limit_reached,
        )

    def _publish(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        for observer in self._observers.get(session_id, ()):
            observer.publish(lambda: self._create_snapshot(session_id, session))

    def close_observers(self) -> None:
        self._observers_closed = True
        for observers in self._observers.values():
            for observer in observers:
                observer.close()

    async def observe(self, session_id: str, *, owner: ApplicationIdentity) -> AsyncGenerator[SessionSnapshot, None]:
        """Yield detached boundary snapshots; disconnect never controls execution."""
        session = self._require_session(session_id, owner)
        observers = self._observers.setdefault(session_id, set())
        if len(observers) >= MAX_OBSERVERS_PER_SESSION:
            raise ObservationLimitError("Session observer limit reached.")
        observer = _Observer()
        observers.add(observer)
        try:
            yield self._create_snapshot(session_id, session)
            while True:
                self._require_session(session_id, owner)
                observer.check_overflow()
                if self._observers_closed and observer.queue.empty():
                    return
                timeout = (session.expires_at - self._now()).total_seconds()
                try:
                    snapshot = await asyncio.wait_for(observer.queue.get(), timeout=max(0.0, timeout))
                except TimeoutError:
                    continue
                self._require_session(session_id, owner)
                observer.check_overflow()
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
        owner: ApplicationIdentity,
        agent: Agent[None, str],
        prompt: str,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
        on_admitted: Callable[[], None] | None = None,
    ) -> AgentRunResult[str]:
        """Check access, then await turn execution through settlement."""
        session = self._require_session(session_id, owner)
        with bind_turn_identity(session.owner):
            return await session.state.execute_turn(
                agent,
                prompt,
                usage_limits=usage_limits,
                toolsets=toolsets,
                on_admitted=on_admitted,
            )

