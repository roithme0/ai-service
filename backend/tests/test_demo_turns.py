import asyncio
import json
from datetime import UTC, datetime

from app.agents.agentic_generation import AgenticToolCall
from app.demo.tools.greeting import create_greeting_tool
from app.demo.tools.greetings import create_greetings_tool
from app.demo.session import GreetingsPayload, create_demo_session, new_demo_session_store
from app.demo.agent import create_demo_agent
from app.demo.turns import COMPLETE_REPLY, FIRST_REPLY, SECOND_REPLY
from app.sessions.conversation import (
    ConversationReadActive,
    ConversationTurnReservation,
)
from app.sessions.tools import ToolRegistry, RegisteredTool, ToolExecution, ToolInvocation
from app.demo.session import DemoPayload
from app.sessions.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.sessions.history import ArtifactRecord, CallRecord, ToolResultRecord, ExecutionReportRecord


async def no_delay(seconds: float) -> None:
    return None


def test_scripted_sequence_uses_shared_messages_artifacts_and_new_session_reset() -> None:
    store = new_demo_session_store()
    first_session = create_demo_session(store, owner="test:user")
    delays: list[float] = []

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    store.append_user_message(first_session.session_id, "Anything")
    first = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))
    store.append_user_message(first_session.session_id, "Unrelated text")
    second = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))
    store.append_user_message(first_session.session_id, "More")
    third = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))
    repeated_failure = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))
    store.append_user_message(first_session.session_id, "Again")
    fourth = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))
    store.append_user_message(first_session.session_id, "Still more")
    fifth = asyncio.run(create_demo_agent(store, delay_seconds=0.25, pause=record_delay).execute_turn(first_session.session_id))

    assert [turn.kind for turn in (first, second, third, fourth, fifth)] == [
        "completed", "completed", "generation_failed", "completed", "completed",
    ]
    assert repeated_failure == third
    assert [turn.text for turn in (first, second, third, fourth, fifth)] == [
        FIRST_REPLY, SECOND_REPLY, None, COMPLETE_REPLY, COMPLETE_REPLY,
    ]
    assert fourth.text == fifth.text == "This scripted demo is complete. Refresh the page to restart it."
    assert delays == [0.25] * 16
    assert first.artifacts == third.artifacts == fourth.artifacts == fifth.artifacts == ()
    assert len(second.artifacts) == 2
    artifact = second.artifacts[0]
    assert artifact.artifact_id
    assert artifact.created_at.tzinfo is not None
    assert artifact.order == 9
    assert artifact.turn_id == second.turn_id
    assert artifact.type == "demo.greeting"
    assert artifact.payload.model_dump() == {"message": "Hello, World!"}
    greetings = second.artifacts[1]
    assert greetings.type == "demo.greetings"
    assert greetings.order == 14
    assert greetings.turn_id == second.turn_id
    assert isinstance(greetings.payload, GreetingsPayload)
    assert greetings.payload.messages == tuple(f"Hello, Visitor {index}!" for index in range(1, 31))
    results = [record for record in store.history(first_session.session_id)
               if isinstance(record, ToolResultRecord) and record.turn_id == second.turn_id]
    assert [record.failed for record in results] == [False, False, True]
    assert json.loads(results[-1].output) == {"kind": "rejected", "reason": "invalid_arguments"}
    read = store.read(first_session.session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == (artifact, greetings)
    assert [message.role for message in read.snapshot.session.messages] == [
        "user", "assistant", "user", "assistant", "user", "user", "assistant", "user", "assistant",
    ]
    assert [message.text for message in read.snapshot.session.messages if message.role == "user"] == [
        "Anything", "Unrelated text", "More", "Again", "Still more",
    ]

    next_session = create_demo_session(store, owner="test:user")
    store.append_user_message(next_session.session_id, "Same text as before")
    restarted = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(next_session.session_id))
    assert restarted.text == FIRST_REPLY
    assert restarted.artifacts == ()


def test_greeting_tool_validates_arguments_and_returns_local_candidate() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "Create a greeting")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((create_greeting_tool(),))

    for arguments in ("{", "{}", '{"name":""}', '{"name":4}'):
        result = asyncio.run(registry.invoke("create_greeting", arguments))
        assert json.loads(output_text(result)) == {"kind": "rejected", "reason": "invalid_arguments"}
        assert result.artifact is None
    accepted = asyncio.run(registry.invoke("create_greeting", '{"name":"World"}'))
    assert accepted.artifact is not None
    assert accepted.output == ArtifactToolOutput("created")
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("create", "create", "{}"))
    finalized = store.record_result(session_id, call, accepted)
    published = store.complete_turn(session_id, reservation, "completed", "Created").artifacts
    assert len(published) == 1
    assert published[0].artifact_id == json.loads(output_text(finalized))["artifact_id"]
    assert published[0].payload == accepted.artifact.payload
    assert published[0].order == 4


def test_greetings_tool_validates_list_and_candidate_acceptance() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "Create greetings")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((create_greetings_tool(),))
    for arguments in (
        "{", "{}", '{"names":[]}', '{"names":"World"}', '{"names":[""]}',
        '{"names":["World",4]}', '{"names":["World"," "]}', '{"names":["World"],"extra":true}',
    ):
        result = asyncio.run(registry.invoke("create_greetings", arguments))
        assert json.loads(output_text(result)) == {"kind": "rejected", "reason": "invalid_arguments"}
        assert result.artifact is None
    accepted = asyncio.run(registry.invoke("create_greetings", '{"names":["World","Friend"]}'))
    assert accepted.artifact is not None
    assert isinstance(accepted.artifact.payload, GreetingsPayload)
    assert accepted.artifact.payload.messages == ("Hello, World!", "Hello, Friend!")
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    call = store.record_call(session_id, reservation.turn_id, AgenticToolCall("create", "create", "{}"))
    finalized = store.record_result(session_id, call, accepted)
    published = store.complete_turn(session_id, reservation, "completed", "Created").artifacts
    assert len(published) == 1
    assert published[0].artifact_id == json.loads(output_text(finalized))["artifact_id"]
    assert published[0].payload == accepted.artifact.payload
    assert published[0].order == 4


def test_unaccepted_candidates_are_absent_after_failure_and_retry() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "First")
    assert asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)).kind == "completed"
    store.append_user_message(session_id, "Second")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((
        create_greeting_tool(),
        create_greetings_tool(),
    ))
    assert asyncio.run(registry.invoke("create_greeting", '{"name":"World"}')).artifact is not None
    assert asyncio.run(registry.invoke("create_greetings", '{"names":["World"]}')).artifact is not None
    assert store.fail_turn(session_id, reservation).kind == "generation_failed"
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    store.append_user_message(session_id, "Retry")
    retry = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id))
    assert retry.text == SECOND_REPLY
    assert [artifact.type for artifact in retry.artifacts] == ["demo.greeting", "demo.greetings"]
    assert [artifact.order for artifact in retry.artifacts] == [11, 16]


def test_busy_cancellation_and_retry_keep_first_step() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "Start")
    entered = asyncio.Event()

    async def wait_in_first_turn(seconds: float) -> None:
        entered.set()
        await asyncio.Event().wait()

    async def run() -> None:
        task = asyncio.create_task(create_demo_agent(store, delay_seconds=0.4, pause=wait_in_first_turn).execute_turn(session_id))
        await entered.wait()
        assert (await create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)).kind == "busy"
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
    retry = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id))
    assert retry.text == FIRST_REPLY
    assert retry.artifacts == ()


def test_unaccepted_greeting_does_not_advance_demo_step() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "First")
    assert asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)).kind == "completed"
    store.append_user_message(session_id, "Second")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    registry = ToolRegistry((create_greeting_tool(),))
    assert asyncio.run(registry.invoke("create_greeting", '{"name":"World"}')).artifact is not None
    assert store.fail_turn(session_id, reservation).kind == "generation_failed"
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()
    assert sum(message.role == "assistant" for message in read.snapshot.session.messages) == 1
    assert asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)).kind == "generation_failed"

    store.append_user_message(session_id, "Retry")
    retry = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id))
    assert retry.text == SECOND_REPLY
    assert len(retry.artifacts) == 2
    assert [artifact.order for artifact in retry.artifacts] == [11, 16]


def test_expiry_during_delay_uses_shared_expiry_result() -> None:
    current = datetime(2026, 9, 25, tzinfo=UTC)

    def clock() -> datetime:
        return current

    store = new_demo_session_store(clock)
    created = create_demo_session(store, owner="test:user")
    store.append_user_message(created.session_id, "First")

    async def expire(seconds: float) -> None:
        nonlocal current
        current = created.expires_at

    result = asyncio.run(create_demo_agent(store, delay_seconds=0.4, pause=expire).execute_turn(created.session_id))
    assert result.kind == "expired"
    assert result.artifacts == ()
    assert store.read(created.session_id).kind == "unknown"


def test_scripted_turn_retains_completed_first_tool_when_second_tool_fails() -> None:
    store = new_demo_session_store()
    session_id = create_demo_session(store, owner="test:user").session_id
    store.append_user_message(session_id, "First")
    assert asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)).kind == "completed"
    store.append_user_message(session_id, "Second")

    def failing_factory() -> RegisteredTool[ArtifactCandidate[DemoPayload]]:
        def execute(invocation: ToolInvocation) -> ToolExecution[ArtifactCandidate[DemoPayload]]:
            raise RuntimeError("second tool failed without returning")
        return RegisteredTool("create_greetings", {"type": "function", "name": "create_greetings"}, execute)

    result = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay, greeting_list_tool_factory=failing_factory).execute_turn(session_id))
    assert result.kind == "generation_failed"
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert len(read.snapshot.artifacts) == 1
    assert read.snapshot.artifacts[0].payload.model_dump() == {"message": "Hello, World!"}
    history = store.history(session_id)
    assert len([record for record in history if isinstance(record, CallRecord)]) == 2
    assert len([record for record in history if isinstance(record, ToolResultRecord)]) == 1
    assert len([record for record in history if isinstance(record, ArtifactRecord)]) == 1
    reports = [record for record in history if isinstance(record, ExecutionReportRecord)]
    assert len(reports) == 1
    assert reports[0].state == "outcome_unknown"
    assert asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id)) == result
    store.append_user_message(session_id, "Next")
    next_turn = asyncio.run(create_demo_agent(store, delay_seconds=0, pause=no_delay).execute_turn(session_id))
    assert next_turn.kind == "generation_failed"
    retained = store.read(session_id)
    assert isinstance(retained, ConversationReadActive)
    assert [artifact.order for artifact in retained.snapshot.artifacts] == [9, 20]


def output_text[ArtifactT](execution: ToolExecution[ArtifactT]) -> str:
    assert isinstance(execution.output, str)
    return execution.output
