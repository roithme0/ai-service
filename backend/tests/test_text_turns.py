import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.models.text_generation import TextGenerationRequest, TextGenerationResponse
from app.sessions.text_sessions import (
    MAX_MESSAGE_COUNT,
    EphemeralTextSessionStore,
    TextSessionAppendAccepted,
    TextSessionReadActive,
)
from app.sessions.text_turns import TextTurnCompleted, TextTurnUnavailable, generate_assistant_turn


class FakeGenerator:
    def __init__(self, text: str = "answer") -> None:
        self.text = text
        self.calls: list[TextGenerationRequest] = []
        self.on_generate: type[Exception] | None = None

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        self.calls.append(request)
        if self.on_generate is not None:
            raise self.on_generate("failure")
        return TextGenerationResponse(self.text)


def new_store() -> EphemeralTextSessionStore[str]:
    return EphemeralTextSessionStore(lifetime=timedelta(minutes=5))


def test_generates_one_reply_from_ordered_messages() -> None:
    store = new_store()
    session_id = store.create("payload").session_id
    store.append(session_id, "user", "first")
    store.append(session_id, "assistant", "prior reply")
    store.append(session_id, "user", "second")
    generator = FakeGenerator("  new reply  ")

    outcome = asyncio.run(generate_assistant_turn(store, session_id, generator))
    read = store.read(session_id)

    assert isinstance(outcome, TextTurnCompleted)
    assert outcome.message.role == "assistant"
    assert outcome.message.text == "  new reply  "
    assert [(message.role, message.text) for message in generator.calls[0].messages] == [
        ("user", "first"), ("assistant", "prior reply"), ("user", "second")
    ]
    assert isinstance(read, TextSessionReadActive)
    assert read.session.messages[-1] == outcome.message


def test_missing_or_not_ready_session_does_not_call_generator() -> None:
    store = new_store()
    session_id = store.create("payload").session_id
    generator = FakeGenerator()

    assert asyncio.run(generate_assistant_turn(store, "missing", generator)) == TextTurnUnavailable("unknown")
    assert asyncio.run(generate_assistant_turn(store, session_id, generator)) == TextTurnUnavailable("not_ready")
    store.append(session_id, "user", "question")
    assert isinstance(asyncio.run(generate_assistant_turn(store, session_id, generator)), TextTurnCompleted)
    assert asyncio.run(generate_assistant_turn(store, session_id, generator)) == TextTurnUnavailable("not_ready")
    assert len(generator.calls) == 1


def test_full_session_does_not_call_generator() -> None:
    store = new_store()
    session_id = store.create("payload").session_id
    for index in range(MAX_MESSAGE_COUNT):
        assert isinstance(store.append(session_id, "user", str(index)), TextSessionAppendAccepted)
    generator = FakeGenerator()

    assert asyncio.run(generate_assistant_turn(store, session_id, generator)) == TextTurnUnavailable("limit_reached")
    assert generator.calls == []


def test_generator_failure_is_logged_without_request_details_and_leaves_messages_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = new_store()
    session_id = store.create("payload").session_id
    store.append(session_id, "user", "question")
    generator = FakeGenerator()
    generator.on_generate = RuntimeError

    with caplog.at_level(logging.ERROR, logger="app.sessions.text_turns"):
        outcome = asyncio.run(generate_assistant_turn(store, session_id, generator))
    assert outcome == TextTurnUnavailable("generation_failed")
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == f"Text generation failed for session {session_id} (RuntimeError)"
    assert "question" not in record.getMessage()
    assert record.exc_info is None

    generator.on_generate = None
    generator.text = "  "
    assert asyncio.run(generate_assistant_turn(store, session_id, generator)) == TextTurnUnavailable("generation_failed")
    read = store.read(session_id)
    assert isinstance(read, TextSessionReadActive)
    assert len(read.session.messages) == 1


def test_new_user_message_during_generation_prevents_stale_reply() -> None:
    store = new_store()
    session_id = store.create("payload").session_id
    store.append(session_id, "user", "first")

    class InterleavingGenerator(FakeGenerator):
        async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
            store.append(session_id, "user", "second")
            return await super().generate(request)

    outcome = asyncio.run(generate_assistant_turn(store, session_id, InterleavingGenerator()))
    read = store.read(session_id)

    assert outcome == TextTurnUnavailable("conflict")
    assert isinstance(read, TextSessionReadActive)
    assert [message.text for message in read.session.messages] == ["first", "second"]


def test_expiry_during_generation_prevents_reply() -> None:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    clock = [now]
    store = EphemeralTextSessionStore[str](
        lifetime=timedelta(minutes=5), clock=lambda: clock[0]
    )
    session_id = store.create("payload").session_id
    store.append(session_id, "user", "question")

    class ExpiringGenerator(FakeGenerator):
        async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
            clock[0] += timedelta(minutes=5)
            return await super().generate(request)

    assert asyncio.run(generate_assistant_turn(store, session_id, ExpiringGenerator())) == TextTurnUnavailable("expired")
