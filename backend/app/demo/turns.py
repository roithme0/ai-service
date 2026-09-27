"""Scripted turn selection over the shared conversation lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from app.demo.tools import DemoToolFactory
from app.demo.tools.greeting import create_greeting_tool
from app.demo.tools.greetings import create_greetings_tool
from app.demo.session import DemoPayload, DemoSessionStore
from app.sessions.conversation import ConversationTurnResult
from app.sessions.tools import ToolRegistry


TURN_DELAY_SECONDS = 1.5
FIRST_REPLY = "Hello! This is a scripted chat UI demo. Send another message to see two tools create artifacts."
SECOND_REPLY = "This scripted demo created two greetings artifacts. Expand the longer list to see them all. Send another message to see an error state."
COMPLETE_REPLY = "This scripted demo is complete. Refresh the page to restart it."

logger = logging.getLogger(__name__)


async def run_demo_turn(
    store: DemoSessionStore,
    session_id: str,
    delay_seconds: float = TURN_DELAY_SECONDS,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    single_greeting_tool_factory: DemoToolFactory = create_greeting_tool,
    greeting_list_tool_factory: DemoToolFactory = create_greetings_tool,
) -> ConversationTurnResult[DemoPayload]:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, ConversationTurnResult):
        return reservation

    try:
        await pause(delay_seconds)
        completed_count = sum(message.role == "assistant" for message in reservation.snapshot.messages)
        if completed_count == 0:
            reply = FIRST_REPLY
        elif completed_count == 1:
            registry = ToolRegistry((
                single_greeting_tool_factory(store, session_id, reservation.turn_id),
                greeting_list_tool_factory(store, session_id, reservation.turn_id),
            ))
            greeting = await registry.invoke("create_greeting", '{"name":"World"}')
            if greeting.artifact is None:
                return store.fail_turn(session_id, reservation)
            greetings = await registry.invoke(
                "create_greetings", json.dumps({"names": [f"Visitor {index}" for index in range(1, 31)]})
            )
            if greetings.artifact is None:
                return store.fail_turn(session_id, reservation)
            reply = SECOND_REPLY
        elif completed_count == 2 and reservation.snapshot.messages[-2].role == "assistant":
            return store.fail_turn(session_id, reservation)
        else:
            reply = COMPLETE_REPLY
        return store.complete_turn(session_id, reservation, "completed", reply)
    except asyncio.CancelledError:
        store.fail_turn(session_id, reservation)
        raise
    except Exception:
        logger.exception("Demo turn failed (session_id=%s, turn_id=%s)", session_id, reservation.turn_id)
        return store.fail_turn(session_id, reservation)
