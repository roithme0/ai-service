from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.sessions.conversation import ConversationSessionStore, ConversationTurnReservation, ConversationTurnResult


ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")


async def execute_reserved_turn(
    store: ConversationSessionStore[ContextT, ArtifactT],
    execute: Callable[[str, ConversationTurnReservation[ContextT, ArtifactT]], Awaitable[ConversationTurnResult[ArtifactT]]],
    session_id: str,
) -> ConversationTurnResult[ArtifactT]:
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, ConversationTurnResult):
        return reservation
    return await execute(session_id, reservation)
