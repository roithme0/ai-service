"""Process-local conversation history around native turn execution."""

from collections.abc import Sequence
from copy import deepcopy
from threading import Lock

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.observation import TurnObservation
from app.agentic.turns import execute_turn


class ConversationBusyError(RuntimeError):
    """The conversation already has a running turn."""


class AgentConversation:
    """Retain native history; callers own the agent's context lifetime.

    Snapshots contain internal diagnostic data, not public timeline payloads.
    """

    def __init__(self) -> None:
        self._last_turn: TurnObservation | None = None
        self._turn_lock = Lock()

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        """Detached history settled by the last started turn."""
        return tuple(deepcopy(self._last_turn.messages)) if self._last_turn else ()

    @property
    def last_turn(self) -> TurnObservation | None:
        """Detached inspection of the last settled turn, including failed turns."""
        return deepcopy(self._last_turn)

    async def run_turn(
        self,
        agent: Agent[None, str],
        prompt: str,
        *,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
    ) -> AgentRunResult[str]:
        if not self._turn_lock.acquire(blocking=False):
            raise ConversationBusyError("The conversation already has a running turn.")
        observation = TurnObservation()
        try:
            return await execute_turn(
                agent,
                prompt,
                message_history=self.messages,
                usage_limits=usage_limits,
                observation=observation,
                toolsets=toolsets,
            )
        finally:
            if observation.run_id is not None:
                self._last_turn = observation
            self._turn_lock.release()
