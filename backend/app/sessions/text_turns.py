"""Single-turn text orchestration over an ephemeral session."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, TypeVar

from app.models.text_generation import TextGenerationRequest, TextGenerator, generate_text
from app.sessions.text_sessions import (
    MAX_MESSAGE_COUNT,
    EphemeralTextSessionStore,
    TextMessage,
    TextSessionAppendAccepted,
    TextSessionAppendConflict,
    TextSessionAppendExpired,
    TextSessionAppendLimitReached,
    TextSessionAppendUnknown,
    TextSessionReadActive,
    TextSessionReadExpired,
)


@dataclass(frozen=True)
class TextTurnCompleted:
    kind: Literal["completed"]
    message: TextMessage


@dataclass(frozen=True)
class TextTurnUnavailable:
    kind: Literal["unknown", "expired", "not_ready", "limit_reached", "conflict", "generation_failed"]


TextTurnOutcome = TextTurnCompleted | TextTurnUnavailable
T = TypeVar("T")
logger = logging.getLogger(__name__)


async def generate_assistant_turn(
    store: EphemeralTextSessionStore[T], session_id: str, generator: TextGenerator,
    context: str | None = None,
    instructions: str | None = None,
) -> TextTurnOutcome:
    read = store.read(session_id)
    if isinstance(read, TextSessionReadExpired):
        return TextTurnUnavailable(kind="expired")
    if not isinstance(read, TextSessionReadActive):
        return TextTurnUnavailable(kind="unknown")

    snapshot = read.session
    if not snapshot.messages or snapshot.messages[-1].role != "user":
        return TextTurnUnavailable(kind="not_ready")
    if len(snapshot.messages) >= MAX_MESSAGE_COUNT:
        return TextTurnUnavailable(kind="limit_reached")

    try:
        response = await generate_text(
            generator, TextGenerationRequest(snapshot.messages, context, instructions)
        )
    except Exception as error:
        logger.error(
            "Text generation failed for session %s (%s)",
            session_id,
            type(error).__name__,
        )
        return TextTurnUnavailable(kind="generation_failed")

    appended = store.append_if_revision(session_id, snapshot.revision, "assistant", response.text)
    if isinstance(appended, TextSessionAppendAccepted):
        return TextTurnCompleted(kind="completed", message=appended.message)
    if isinstance(appended, TextSessionAppendExpired):
        return TextTurnUnavailable(kind="expired")
    if isinstance(appended, TextSessionAppendUnknown):
        return TextTurnUnavailable(kind="unknown")
    if isinstance(appended, TextSessionAppendConflict):
        return TextTurnUnavailable(kind="conflict")
    if isinstance(appended, TextSessionAppendLimitReached):
        return TextTurnUnavailable(kind="limit_reached")
    raise AssertionError("validated generator output was rejected by the session store")
