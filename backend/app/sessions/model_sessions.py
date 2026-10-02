"""Configuration of model-backed sessions with caller-provided context."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Never

from app.models.agentic_generation import AgenticGenerator
from app.sessions.agent_service import ConfiguredAgentService
from app.sessions.context import ContextIssue, SessionContext, format_session_context, validate_context_input
from app.sessions.conversation import ConversationSessionSettings, ConversationSessionStore
from app.sessions.instructions import CONVERSATION_INSTRUCTIONS
from app.sessions.model_turns import MAX_PROVIDER_RESPONSES, MAX_TOOL_ATTEMPTS, ModelTurnStrategy
from app.sessions.tools import ToolSource

ModelAgent = ConfiguredAgentService[object, SessionContext, Never, ContextIssue]
ModelSessionStore = ConversationSessionStore[SessionContext, Never]
SESSION_LIFETIME = timedelta(minutes=90)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def new_model_session_store(clock: Callable[[], datetime] = _utc_now) -> ModelSessionStore:
    return ConversationSessionStore(lifetime=SESSION_LIFETIME, clock=clock)


def create_model_agent(
    generator: AgenticGenerator,
    store: ModelSessionStore | None = None,
    *,
    instructions: str = CONVERSATION_INSTRUCTIONS,
    max_artifacts: int = 20,
    max_tool_attempts: int = MAX_TOOL_ATTEMPTS,
    max_provider_responses: int = MAX_PROVIDER_RESPONSES,
    tool_sources: tuple[ToolSource[Never], ...] = (),
) -> ModelAgent:
    owned_store = store if store is not None else new_model_session_store()
    return ConfiguredAgentService(
        owned_store, validate_context_input,
        ModelTurnStrategy(
            owned_store, generator, format_session_context, tool_sources,
            instructions=instructions, max_attempts=max_tool_attempts,
            max_provider_responses=max_provider_responses,
        ),
        ConversationSessionSettings(max_artifacts=max_artifacts),
    )
