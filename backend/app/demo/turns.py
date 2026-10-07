"""Scripted turn selection over the shared conversation lifecycle."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from app.agents.agentic_generation import AgenticGenerationResponse, AgenticToolCall
from app.demo.tools import DemoToolFactory
from app.demo.tools.greeting import create_greeting_tool
from app.demo.tools.greetings import create_greetings_tool
from app.demo.session import DemoContext, DemoPayload, DemoSessionStore
from app.sessions.conversation import ConversationTurnReservation, ConversationTurnResult, TurnHistoryUnavailable
from app.sessions.tools import ToolRegistry


TURN_DELAY_SECONDS = 1.5
FIRST_REPLY = "Hello! This is a scripted chat UI demo. Send another message to see two tools create artifacts."
SECOND_REPLY = "This scripted demo created two greetings artifacts. Expand the longer list to see them all. An additional greeting call deliberately used an empty name and failed validation, so it created no artifact. Send another message to see an error state."
FIRST_TOOL_UPDATE = "I'll create a single greeting first."
SECOND_TOOL_UPDATE = "The single greeting is ready. Next I'll create a list of 30 greetings to demonstrate expanding a larger artifact."
FAILED_TOOL_UPDATE = "Both artifacts are ready. I'll now deliberately try an empty name to show how a failed tool call appears."
FAILED_GENERATION_UPDATE = "I'll start another response. This demo will deliberately stop generation after this update, leaving it visible without a final answer."
COMPLETE_REPLY = "This scripted demo is complete. Refresh the page to restart it."

logger = logging.getLogger(__name__)


async def run_demo_turn(
    store: DemoSessionStore,
    session_id: str,
    reservation: ConversationTurnReservation[DemoContext, DemoPayload],
    delay_seconds: float = TURN_DELAY_SECONDS,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    single_greeting_tool_factory: DemoToolFactory = create_greeting_tool,
    greeting_list_tool_factory: DemoToolFactory = create_greetings_tool,
) -> ConversationTurnResult[DemoPayload]:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    try:
        await pause(delay_seconds)
        completed_count = sum(message.role == "assistant" for message in reservation.snapshot.messages)
        if completed_count == 0:
            reply = FIRST_REPLY
        elif completed_count == 1:
            registry = ToolRegistry((
                single_greeting_tool_factory(),
                greeting_list_tool_factory(),
            ))
            store.record_provider_response(session_id, reservation.turn_id, AgenticGenerationResponse((
                {"type": "message", "role": "assistant", "phase": "commentary", "content": FIRST_TOOL_UPDATE},
            ), (), FIRST_TOOL_UPDATE))
            call = store.record_call(session_id, reservation.turn_id,
                                     AgenticToolCall("greeting", "create_greeting", '{"name":"World"}'))
            await pause(delay_seconds)
            store.start_execution(session_id, call)
            await pause(delay_seconds)
            greeting = await registry.invoke(call.call.name, call.call.arguments)
            greeting = store.record_result(session_id, call, greeting)
            if greeting.artifact is None:
                return store.fail_turn(session_id, reservation)
            store.record_provider_response(session_id, reservation.turn_id, AgenticGenerationResponse((
                {"type": "message", "role": "assistant", "phase": "commentary", "content": SECOND_TOOL_UPDATE},
            ), (), SECOND_TOOL_UPDATE))
            call = store.record_call(session_id, reservation.turn_id, AgenticToolCall(
                "greetings", "create_greetings", json.dumps({"names": [f"Visitor {index}" for index in range(1, 31)]})))
            await pause(delay_seconds)
            store.start_execution(session_id, call)
            await pause(delay_seconds)
            greetings = await registry.invoke(call.call.name, call.call.arguments)
            greetings = store.record_result(session_id, call, greetings)
            if greetings.artifact is None:
                return store.fail_turn(session_id, reservation)
            store.record_provider_response(session_id, reservation.turn_id, AgenticGenerationResponse((
                {"type": "message", "role": "assistant", "phase": "commentary", "content": FAILED_TOOL_UPDATE},
            ), (), FAILED_TOOL_UPDATE))
            call = store.record_call(session_id, reservation.turn_id,
                                     AgenticToolCall("invalid-greeting", "create_greeting", '{"name":""}'))
            await pause(delay_seconds)
            store.start_execution(session_id, call)
            await pause(delay_seconds)
            rejected = await registry.invoke(call.call.name, call.call.arguments)
            rejected = store.record_result(session_id, call, rejected)
            if not rejected.failed or rejected.artifact is not None:
                return store.fail_turn(session_id, reservation)
            reply = SECOND_REPLY
        elif completed_count == 2 and reservation.snapshot.messages[-2].role == "assistant":
            store.record_provider_response(session_id, reservation.turn_id, AgenticGenerationResponse((
                {"type": "message", "role": "assistant", "phase": "commentary", "content": FAILED_GENERATION_UPDATE},
            ), (), FAILED_GENERATION_UPDATE))
            await pause(delay_seconds)
            return store.fail_turn(session_id, reservation)
        else:
            reply = COMPLETE_REPLY
        store.record_provider_item(session_id, reservation.turn_id, {"type": "message", "role": "assistant", "phase": "final_answer", "content": reply})
        await pause(delay_seconds)
        return store.complete_turn(session_id, reservation, "completed", reply)
    except TurnHistoryUnavailable as error:
        return ConversationTurnResult(error.kind, reservation.turn_id, None, ())
    except asyncio.CancelledError:
        store.fail_turn(session_id, reservation)
        raise
    except Exception:
        logger.exception("Demo turn failed (session_id=%s, turn_id=%s)", session_id, reservation.turn_id)
        return store.fail_turn(session_id, reservation)
