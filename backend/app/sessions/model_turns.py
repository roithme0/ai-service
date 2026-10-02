"""Artifact-free model turns over the shared conversation lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Generic, Never, TypeVar

from app.models.agentic_generation import AgenticGenerator
from app.sessions.conversation import ConversationSessionStore, ConversationTurnResult
from app.sessions.instructions import CONVERSATION_INSTRUCTIONS
from app.sessions.tool_turns import run_tool_turn
from app.sessions.tools import ToolSource


ContextT = TypeVar("ContextT")
MAX_TOOL_ATTEMPTS = 6
MAX_PROVIDER_RESPONSES = 8
logger = logging.getLogger(__name__)


class ModelTurnStrategy(Generic[ContextT]):
    def __init__(
        self,
        store: ConversationSessionStore[ContextT, Never],
        generator: AgenticGenerator,
        context: Callable[[ContextT], str],
        tool_sources: tuple[ToolSource[Never], ...],
        *,
        instructions: str = CONVERSATION_INSTRUCTIONS,
        max_attempts: int = MAX_TOOL_ATTEMPTS,
        max_provider_responses: int = MAX_PROVIDER_RESPONSES,
    ) -> None:
        if not instructions.strip():
            raise ValueError("instructions must not be blank")
        if min(max_attempts, max_provider_responses) < 1:
            raise ValueError("model turn limits must be positive")
        self._store = store
        self._generator = generator
        self._context = context
        self._tool_sources = tool_sources
        self._instructions = instructions
        self._max_attempts = max_attempts
        self._max_provider_responses = max_provider_responses

    async def __call__(self, session_id: str) -> ConversationTurnResult[Never]:
        reservation = self._store.reserve_turn(session_id)
        if isinstance(reservation, ConversationTurnResult):
            return reservation
        try:
            result = await run_tool_turn(
                self._generator, reservation.snapshot.messages,
                self._context(reservation.snapshot.payload), self._instructions,
                self._tool_sources, self._max_attempts,
                max_successes=None, max_provider_responses=self._max_provider_responses,
            )
            return self._store.complete_turn(session_id, reservation, result.kind, result.text)
        except asyncio.CancelledError:
            self._store.fail_turn(session_id, reservation)
            raise
        except Exception:
            logger.exception("Model turn failed (session_id=%s, turn_id=%s)", session_id, reservation.turn_id)
            return self._store.fail_turn(session_id, reservation)
