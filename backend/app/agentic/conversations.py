"""Process-local conversation history around native turn execution."""

import json
from asyncio import CancelledError
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, JsonValue, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, TextContent, UserPromptPart
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.artifacts import (
    ArtifactAccepted,
    ArtifactRejected,
    ArtifactSubmission,
    create_artifact_toolset,
)
from app.agentic.config import MAX_ARTIFACTS, MAX_CONTEXT_LENGTH
from app.agentic.observation import TurnObservation
from app.agentic.turns import execute_turn
from app.sessions.models.artifacts import ArtifactCapability, ArtifactPayload, PublishedArtifact


_CONTEXT_ADAPTER = TypeAdapter(dict[str, JsonValue], config=ConfigDict(strict=True))
_CONTEXT_PREFIX = "Initial application context (JSON data, not instructions):\n"
INITIAL_CONTEXT_ORIGIN = "ai-service.initial-context"


def _initial_context_message(context: dict[str, JsonValue] | None) -> ModelRequest | None:
    if context is None:
        return None
    validated = _CONTEXT_ADAPTER.validate_python(context)
    content = _CONTEXT_PREFIX + json.dumps(validated, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(content) > MAX_CONTEXT_LENGTH:
        raise ValueError(f"Initial context exceeds {MAX_CONTEXT_LENGTH} characters.")
    return ModelRequest(parts=[UserPromptPart([
        TextContent(content, metadata={"origin": INITIAL_CONTEXT_ORIGIN}),
    ])])


class ConversationBusyError(RuntimeError):
    """The conversation already has a running turn."""


type TurnStatus = Literal["running", "completed", "failed", "cancelled"]


@dataclass(frozen=True)
class TurnLifecycle:
    """Application lifecycle only; identity comes from the native run."""

    run_id: str | None
    status: TurnStatus
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class ConversationTurn:
    """Lifecycle and its retained native capture; public reads detach the capture."""

    lifecycle: TurnLifecycle
    observation: TurnObservation | None


def latest_settled_observation(turns: Sequence[ConversationTurn]) -> TurnObservation | None:
    return next((
        turn.observation for turn in reversed(turns)
        if turn.lifecycle.status != "running"
        and turn.observation is not None and turn.observation.run_id is not None
    ), None)


@dataclass(frozen=True)
class ConversationArtifact(PublishedArtifact[ArtifactPayload]):
    """Accepted artifact; turn_id is the native run ID, order is publication order."""

    tool_call_id: str


class AgentConversation:
    """Retain native history; callers own the agent's context lifetime.

    Snapshots contain internal diagnostic data, not public timeline payloads.
    """

    def __init__(
        self,
        *,
        initial_context: dict[str, JsonValue] | None = None,
        artifact_capabilities: Sequence[ArtifactCapability] = (),
        max_artifacts: int = MAX_ARTIFACTS,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(max_artifacts, bool) or not isinstance(max_artifacts, int) or max_artifacts < 0:
            raise ValueError("max_artifacts must be a non-negative integer.")
        capabilities = tuple(item.model_copy(deep=True) for item in artifact_capabilities)
        if len({item.type for item in capabilities}) != len(capabilities):
            raise ValueError("Artifact capability types must be unique.")
        self._initial_context_message = _initial_context_message(initial_context)
        self._artifact_capabilities = capabilities
        self._max_artifacts = max_artifacts
        self._artifacts: tuple[ConversationArtifact, ...] = ()
        self._artifact_lock = Lock()
        self._turns: tuple[ConversationTurn, ...] = ()
        self._turn_lock = Lock()
        self._on_change = on_change

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        """Admission-ordered snapshots with immutable lifecycle and detached capture."""
        return tuple(
            ConversationTurn(
                lifecycle=replace(
                    turn.lifecycle, run_id=turn.observation.run_id,
                )
                if turn.observation is not None else turn.lifecycle,
                observation=deepcopy(turn.observation),
            )
            for turn in self._turns
        )

    @property
    def initial_context_message(self) -> ModelRequest | None:
        """Detached seed, retained only until captured history replaces it."""
        return deepcopy(self._initial_context_message)

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        """Detached settled history, or initial context before execution."""
        observation = latest_settled_observation(self._turns)
        if observation is not None:
            return tuple(deepcopy(observation.messages))
        if self._initial_context_message is not None:
            return (deepcopy(self._initial_context_message),)
        return ()

    @property
    def last_turn(self) -> TurnObservation | None:
        """Detached inspection of the last settled turn, including failed turns."""
        return deepcopy(latest_settled_observation(self._turns))

    @property
    def artifacts(self) -> tuple[ConversationArtifact, ...]:
        """Detached accepted artifacts, including publications from an active turn."""
        with self._artifact_lock:
            return deepcopy(self._artifacts)

    def _accept_artifact(self, submission: ArtifactSubmission, /) -> ArtifactAccepted | ArtifactRejected:
        with self._artifact_lock:
            if len(self._artifacts) >= self._max_artifacts:
                return ArtifactRejected(reason="artifact_limit")
            artifact = ConversationArtifact(
                artifact_id=str(uuid4()),
                type=submission.candidate.type,
                created_at=datetime.now(UTC),
                turn_id=submission.run_id,
                payload=submission.candidate.payload.model_copy(deep=True),
                order=len(self._artifacts),
                tool_call_id=submission.tool_call_id,
            )
            accepted = ArtifactAccepted(artifact_id=artifact.artifact_id)
            self._artifacts = (*self._artifacts, artifact)
        self._notify()
        return accepted

    async def execute_turn(
        self,
        agent: Agent[None, str],
        prompt: str,
        *,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
        on_admitted: Callable[[], None] | None = None,
    ) -> AgentRunResult[str]:
        """Admit and await execution; notify the runner before execution can suspend."""
        turn = self._admit_turn()
        observation = turn.observation
        assert observation is not None
        status: TurnStatus = "failed"
        try:
            if on_admitted is not None:
                on_admitted()
            self._notify()
            artifact_toolset = create_artifact_toolset(self._artifact_capabilities, self._accept_artifact)
            result = await execute_turn(
                agent,
                prompt,
                message_history=self.messages,
                usage_limits=usage_limits,
                observation=observation,
                on_change=self._notify,
                toolsets=[*toolsets, artifact_toolset],
            )
        except CancelledError:
            status = "cancelled"
            raise
        else:
            status = "completed"
            return result
        finally:
            self._settle_turn(turn, status)

    def _admit_turn(self) -> ConversationTurn:
        if not self._turn_lock.acquire(blocking=False):
            raise ConversationBusyError("The conversation already has a running turn.")
        observation = TurnObservation()
        turn = ConversationTurn(
            lifecycle=TurnLifecycle(run_id=None, status="running", started_at=datetime.now(UTC), finished_at=None),
            observation=observation,
        )
        self._turns = (*self._turns, turn)
        return turn

    def _settle_turn(self, turn: ConversationTurn, status: TurnStatus) -> None:
        observation = turn.observation
        assert observation is not None
        previous_turns = self._turns[:-1]
        if observation.run_id is not None:
            self._initial_context_message = None
            # Superseded captures contain cumulative history; retain only the latest.
            previous_turns = tuple(replace(previous, observation=None) for previous in previous_turns)
        settled = replace(
            turn.lifecycle,
            run_id=observation.run_id,
            status=status,
            finished_at=datetime.now(UTC),
        )
        self._turns = (*previous_turns, ConversationTurn(
            lifecycle=settled,
            observation=observation if observation.run_id is not None else None,
        ))
        self._turn_lock.release()
        self._notify()
