"""Project retained history into session messages."""

from __future__ import annotations

from app.agents.generation_messages import message_text
from app.sessions.models.history import HistoryRecord, MessageRecord, TerminalRecord
from app.sessions.models.session import TextMessage


def text_messages(history: tuple[HistoryRecord, ...]) -> tuple[TextMessage, ...]:
    completed = {record.turn_id for record in history
                 if isinstance(record, TerminalRecord) and record.kind == "completed"}
    emitted: set[str] = set()
    messages: list[TextMessage] = []
    for record in history:
        if not isinstance(record, MessageRecord):
            continue
        if record.kind == "user":
            messages.append(TextMessage("user", message_text(record.item)))
        elif record.kind == "final" and record.turn_id in completed and record.turn_id not in emitted:
            messages.append(TextMessage("assistant", message_text(record.item), record.turn_id))
            emitted.add(record.turn_id)
    return tuple(messages)
