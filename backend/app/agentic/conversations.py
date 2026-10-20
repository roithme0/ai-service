"""Process-local conversation history around native turn execution."""

import json
from collections.abc import Sequence
from copy import deepcopy
from threading import Lock

from pydantic import ConfigDict, JsonValue, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import MAX_CONTEXT_LENGTH
from app.agentic.observation import TurnObservation
from app.agentic.turns import execute_turn


_CONTEXT_ADAPTER = TypeAdapter(dict[str, JsonValue], config=ConfigDict(strict=True))
_CONTEXT_PREFIX = "Initial application context (JSON data, not instructions):\n"


def _initial_context_message(context: dict[str, JsonValue] | None) -> ModelRequest | None:
    if context is None:
        return None
    validated = _CONTEXT_ADAPTER.validate_python(context)
    content = _CONTEXT_PREFIX + json.dumps(validated, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(content) > MAX_CONTEXT_LENGTH:
        raise ValueError(f"Initial context exceeds {MAX_CONTEXT_LENGTH} characters.")
    return ModelRequest(parts=[UserPromptPart(content)])


class ConversationBusyError(RuntimeError):
    """The conversation already has a running turn."""


class AgentConversation:
    """Retain native history; callers own the agent's context lifetime.

    Snapshots contain internal diagnostic data, not public timeline payloads.
    """

    def __init__(self, *, initial_context: dict[str, JsonValue] | None = None) -> None:
        self._initial_context_message = _initial_context_message(initial_context)
        self._last_turn: TurnObservation | None = None
        self._turn_lock = Lock()

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        """Detached settled history, or initial context before execution."""
        if self._last_turn is not None:
            return tuple(deepcopy(self._last_turn.messages))
        if self._initial_context_message is not None:
            return (deepcopy(self._initial_context_message),)
        return ()

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
                self._initial_context_message = None
            self._turn_lock.release()
