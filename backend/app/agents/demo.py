"""Deterministic demo agent configuration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.demo.tools import DemoToolFactory
from app.demo.tools.greeting import create_greeting_tool
from app.demo.tools.greetings import create_greetings_tool
from app.demo.session import DemoContext, DemoPayload, DemoSessionStore, MAX_ARTIFACTS, new_demo_session_store
from app.demo.turns import TURN_DELAY_SECONDS, run_demo_turn
from app.sessions.agent_service import AgentInputAccepted, AgentInputRejected, ConfiguredAgentService
from app.sessions.conversation import ConversationSessionSettings, ConversationTurnResult


DemoSessionInput = object
DemoAgent = ConfiguredAgentService[DemoSessionInput, DemoContext, DemoPayload, str]


def validate_demo_input(
    value: DemoSessionInput,
) -> AgentInputAccepted[DemoContext] | AgentInputRejected[str]:
    if value is None or (isinstance(value, dict) and not value):
        return AgentInputAccepted(DemoContext())
    return AgentInputRejected(("demo input must be absent or an empty object",))


def create_demo_agent(
    store: DemoSessionStore | None = None,
    *,
    delay_seconds: float = TURN_DELAY_SECONDS,
    max_artifacts: int = MAX_ARTIFACTS,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    single_greeting_tool_factory: DemoToolFactory = create_greeting_tool,
    greeting_list_tool_factory: DemoToolFactory = create_greetings_tool,
) -> DemoAgent:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    owned_store = store if store is not None else new_demo_session_store()

    async def execute(session_id: str) -> ConversationTurnResult[DemoPayload]:
        return await run_demo_turn(
            owned_store,
            session_id,
            delay_seconds=delay_seconds,
            pause=pause,
            single_greeting_tool_factory=single_greeting_tool_factory,
            greeting_list_tool_factory=greeting_list_tool_factory,
        )

    return ConfiguredAgentService(
        owned_store, validate_demo_input, execute,
        ConversationSessionSettings(max_artifacts=max_artifacts),
    )
