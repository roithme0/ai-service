"""Scripted turn selection over the shared conversation lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.demo.greeting import DemoToolFactory, create_greeting_tool
from app.demo.session import DemoSessionStore, GreetingPayload
from app.sessions.conversation import ConversationTurnResult
from app.sessions.tools import ToolRegistry


FIRST_TURN_DELAY_SECONDS = 0.4
FIRST_REPLY = "Hello! This is a scripted chat UI demo. Send another message to see a tool create an artifact."
SECOND_REPLY = "This scripted demo created a greeting artifact. Send another message to finish."
COMPLETE_REPLY = "This scripted demo is complete. Start a new session to restart it."

logger = logging.getLogger(__name__)


async def run_demo_turn(
    store: DemoSessionStore,
    session_id: str,
    first_turn_delay_seconds: float = FIRST_TURN_DELAY_SECONDS,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    tool_factory: DemoToolFactory = create_greeting_tool,
) -> ConversationTurnResult[GreetingPayload]:
    if first_turn_delay_seconds < 0:
        raise ValueError("first_turn_delay_seconds must not be negative")
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, ConversationTurnResult):
        return reservation

    try:
        completed_count = sum(message.role == "assistant" for message in reservation.snapshot.messages)
        if completed_count == 0:
            await pause(first_turn_delay_seconds)
            reply = FIRST_REPLY
        elif completed_count == 1:
            registry = ToolRegistry((tool_factory(store, session_id, reservation.turn_id),))
            execution = await registry.invoke("create_greeting", '{"name":"World"}')
            if execution.artifact is None:
                return store.fail_turn(session_id, reservation)
            reply = SECOND_REPLY
        else:
            reply = COMPLETE_REPLY
        return store.complete_turn(session_id, reservation, "completed", reply)
    except asyncio.CancelledError:
        store.fail_turn(session_id, reservation)
        raise
    except Exception:
        logger.exception("Demo turn failed (session_id=%s, turn_id=%s)", session_id, reservation.turn_id)
        return store.fail_turn(session_id, reservation)
