import asyncio
import json
from datetime import UTC, datetime

from app.demo.greeting import create_greeting_tool
from app.demo.session import create_demo_session, new_demo_session_store
from app.demo.turns import COMPLETE_REPLY, FIRST_REPLY, SECOND_REPLY, run_demo_turn
from app.sessions.conversation import (
    ConversationReadActive,
    ConversationTurnReservation,
)
from app.sessions.tools import ToolRegistry


async def no_delay(seconds: float) -> None:
    return None


def test_scripted_sequence_uses_shared_messages_artifacts_and_new_session_reset() -> None:
    store = new_demo_session_store()
    first_session = create_demo_session(store)
    delays: list[float] = []

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    store.append_user_message(first_session.session_id, "Anything")
    first = asyncio.run(run_demo_turn(store, first_session.session_id, 0.25, record_delay))
    store.append_user_message(first_session.session_id, "Unrelated text")
    second = asyncio.run(run_demo_turn(store, first_session.session_id, 0.25, record_delay))
    store.append_user_message(first_session.session_id, "More")
    third = asyncio.run(run_demo_turn(store, first_session.session_id, 0.25, record_delay))
    store.append_user_message(first_session.session_id, "Again")
    fourth = asyncio.run(run_demo_turn(store, first_session.session_id, 0.25, record_delay))

    assert [turn.kind for turn in (first, second, third, fourth)] == ["completed"] * 4
    assert [turn.text for turn in (first, second, third, fourth)] == [
        FIRST_REPLY, SECOND_REPLY, COMPLETE_REPLY, COMPLETE_REPLY,
    ]
    assert third.text == fourth.text == "This scripted demo is complete. Refresh the page to restart it."
    assert delays == [0.25]
    assert first.artifacts == third.artifacts == fourth.artifacts == ()
    assert len(second.artifacts) == 1
    artifact = second.artifacts[0]
    assert artifact.artifact_id
    assert artifact.created_at.tzinfo is not None
    assert artifact.order == 1
    assert artifact.turn_id == second.turn_id
    assert artifact.type == "demo.greeting"
    assert artifact.payload.model_dump() == {"message": "Hello, World!"}
    read = store.read(first_session.session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == (artifact,)
    assert [message.role for message in read.snapshot.session.messages] == ["user", "assistant"] * 4
    assert [message.text for message in read.snapshot.session.messages if message.role == "user"] == [
        "Anything", "Unrelated text", "More", "Again",
    ]

    next_session = create_demo_session(store)
    store.append_user_message(next_session.session_id, "Same text as before")
    restarted = asyncio.run(run_demo_turn(store, next_session.session_id, 0, no_delay))
    assert restarted.text == FIRST_REPLY
    assert restarted.artifacts == ()


def test_greeting_tool_validates_arguments_and_stages_only_accepted_artifact() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store).session_id
    store.append_user_message(session_id, "Create a greeting")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((create_greeting_tool(store, session_id, reservation.turn_id),))

    for arguments in ("{", "{}", '{"name":""}', '{"name":4}'):
        result = asyncio.run(registry.invoke("create_greeting", arguments))
        assert json.loads(result.output) == {"kind": "rejected", "reason": "invalid_arguments"}
        assert result.artifact is None
    accepted = asyncio.run(registry.invoke("create_greeting", '{"name":"World"}'))
    assert accepted.artifact is not None
    assert json.loads(accepted.output) == {
        "kind": "created", "artifact_id": accepted.artifact.artifact_id,
    }
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    assert store.complete_turn(session_id, reservation, "completed", "Created").artifacts == (accepted.artifact,)


def test_busy_cancellation_and_retry_keep_first_step() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store).session_id
    store.append_user_message(session_id, "Start")
    entered = asyncio.Event()

    async def wait_in_first_turn(seconds: float) -> None:
        entered.set()
        await asyncio.Event().wait()

    async def run() -> None:
        task = asyncio.create_task(run_demo_turn(store, session_id, 0.4, wait_in_first_turn))
        await entered.wait()
        assert (await run_demo_turn(store, session_id, 0, no_delay)).kind == "busy"
        assert store.append_user_message(session_id, "Blocked").kind == "busy"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled demo turn should raise")

    asyncio.run(run())
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.terminal_turn_kind == "generation_failed"
    assert len(read.snapshot.session.messages) == 1
    assert store.reserve_turn(session_id).kind == "generation_failed"
    store.append_user_message(session_id, "Retry")
    retry = asyncio.run(run_demo_turn(store, session_id, 0, no_delay))
    assert retry.text == FIRST_REPLY
    assert retry.artifacts == ()


def test_failed_second_turn_discards_greeting_and_retries_second_step() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store).session_id
    store.append_user_message(session_id, "First")
    assert asyncio.run(run_demo_turn(store, session_id, 0, no_delay)).kind == "completed"
    store.append_user_message(session_id, "Second")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((create_greeting_tool(store, session_id, reservation.turn_id),))
    assert asyncio.run(registry.invoke("create_greeting", '{"name":"World"}')).artifact is not None
    assert store.fail_turn(session_id, reservation).kind == "generation_failed"
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    assert sum(message.role == "assistant" for message in read.snapshot.session.messages) == 1
    assert asyncio.run(run_demo_turn(store, session_id, 0, no_delay)).kind == "generation_failed"

    store.append_user_message(session_id, "Retry")
    retry = asyncio.run(run_demo_turn(store, session_id, 0, no_delay))
    assert retry.text == SECOND_REPLY
    assert len(retry.artifacts) == 1
    assert retry.artifacts[0].order == 1


def test_expiry_during_delay_uses_shared_expiry_result() -> None:
    current = datetime(2026, 9, 25, tzinfo=UTC)

    def clock() -> datetime:
        return current

    store = new_demo_session_store(clock)
    created = create_demo_session(store)
    store.append_user_message(created.session_id, "First")

    async def expire(seconds: float) -> None:
        nonlocal current
        current = created.expires_at

    result = asyncio.run(run_demo_turn(store, created.session_id, 0.4, expire))
    assert result.kind == "expired"
    assert result.artifacts == ()
    assert store.read(created.session_id).kind == "unknown"
