"""Model turns with optional session-specific tools over the conversation lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Generic, TypeVar

from app.agents.protocols.generation import AgenticGenerator
from app.sessions.session_store import ConversationSessionStore, TurnHistoryUnavailable
from app.sessions.models.conversation import ConversationTurnReservation, ConversationTurnResult
from app.agents.history_projection import model_input
from app.sessions.models.artifacts import ArtifactCandidate
from app.sessions.instructions import CONVERSATION_INSTRUCTIONS
from app.agents.tool_turns import run_tool_turn
from app.agents.protocols.tools import ToolSource
from app.sessions.web_search import WebSearchConfig


ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")
MAX_TOOL_ATTEMPTS = 32
MAX_PROVIDER_RESPONSES = 40
logger = logging.getLogger(__name__)


class ModelTurnStrategy(Generic[ContextT, ArtifactT]):
    def __init__(
        self,
        store: ConversationSessionStore[ContextT, ArtifactT],
        generator: AgenticGenerator,
        context: Callable[[ContextT], str],
        tool_sources: tuple[ToolSource[ArtifactCandidate[ArtifactT]], ...],
        *,
        session_tool_sources: Callable[[ContextT, str, str], tuple[ToolSource[ArtifactCandidate[ArtifactT]], ...]] | None = None,
        instructions: str = CONVERSATION_INSTRUCTIONS,
        max_attempts: int = MAX_TOOL_ATTEMPTS,
        max_provider_responses: int = MAX_PROVIDER_RESPONSES,
        web_search: WebSearchConfig | None = None,
    ) -> None:
        if not instructions.strip():
            raise ValueError("instructions must not be blank")
        if min(max_attempts, max_provider_responses) < 1:
            raise ValueError("model turn limits must be positive")
        self._store = store
        self._generator = generator
        self._context = context
        self._tool_sources = tool_sources
        self._session_tool_sources = session_tool_sources
        self._instructions = instructions
        self._max_attempts = max_attempts
        self._max_provider_responses = max_provider_responses
        self._web_search = web_search

    async def __call__(self, session_id: str, reservation: ConversationTurnReservation[ContextT, ArtifactT]) -> ConversationTurnResult[ArtifactT]:
        try:
            session_sources = (
                self._session_tool_sources(reservation.snapshot.payload, session_id, reservation.turn_id)
                if self._session_tool_sources is not None else ()
            )
            result = await run_tool_turn(
                self._generator, model_input(self._store.history(session_id)),
                self._context(reservation.snapshot.payload), self._instructions,
                (*self._tool_sources, *session_sources), self._max_attempts,
                max_successes=None, max_provider_responses=self._max_provider_responses,
                record_item=lambda item: self._store.record_provider_item(session_id, reservation.turn_id, item),
                start_execution=lambda call: self._store.start_execution(session_id, call),
                record_result=lambda call, execution: self._store.record_result(session_id, call, execution),
                web_search=self._web_search,
            )
            return self._store.complete_turn(session_id, reservation, result.kind, result.text)
        except TurnHistoryUnavailable as error:
            return ConversationTurnResult(error.kind, reservation.turn_id, None, ())
        except asyncio.CancelledError:
            self._store.fail_turn(session_id, reservation)
            raise
        except Exception:
            logger.exception("Model turn failed (session_id=%s, turn_id=%s)", session_id, reservation.turn_id)
            return self._store.fail_turn(session_id, reservation)
