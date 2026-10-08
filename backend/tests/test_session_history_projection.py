from app.sessions.history import completed_text_messages
from app.sessions.models.history import HistoryRecord, MessageRecord, TerminalRecord
from app.sessions.timeline import timeline


def test_message_projections_use_retained_text_without_interpreting_replay_payloads() -> None:
    history: tuple[HistoryRecord, ...] = (
        MessageRecord("turn", {"opaque": "user payload"}, "Question", "user"),
        MessageRecord("turn", {"opaque": "update payload"}, "Working", "intermediate"),
        MessageRecord("turn", {"opaque": "answer payload"}, "Answer", "final"),
        TerminalRecord("turn", "completed"),
    )
    messages = completed_text_messages(history)
    assert [(message.role, message.text) for message in messages] == [
        ("user", "Question"), ("assistant", "Answer"),
    ]
    assert messages[-1].turn_id == "turn"
    items = timeline(history)
    assert [(item.kind, item.text) for item in items if item.kind in {"message", "intermediate"}] == [
        ("message", "Question"), ("intermediate", "Working"), ("message", "Answer"),
    ]
