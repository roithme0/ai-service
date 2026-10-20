"""Internal owner-scoped session storage for the native agent runner."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import DEFAULT_SESSION_LIFETIME, MAX_ARTIFACTS
from app.agentic.conversations import (
    AgentConversation,
    ConversationArtifact,
    ConversationTurn,
    latest_settled_observation,
)
from app.agentic.observation import TurnObservation
from app.sessions.models.artifacts import ArtifactCapability


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SessionNotFoundError(LookupError):
    """The session is unknown, expired, or belongs to another owner."""


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
        conversation = AgentConversation(
            initial_context=initial_context,
            artifact_capabilities=artifact_capabilities,
            max_artifacts=max_artifacts,
        )
        session_id = str(uuid4())
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
        conversation = session.conversation
        return SessionSnapshot(
            session_id=session_id,
            expires_at=session.expires_at,
            artifacts=conversation.artifacts,
            turns=conversation.turns,
            initial_context_message=conversation.initial_context_message,
        )

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

