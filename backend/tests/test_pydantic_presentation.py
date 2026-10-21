import asyncio
from collections.abc import Sequence
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from pydantic_ai import Tool, models
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    TextContent,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
    repair_messages,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agentic.conversations import (
    INITIAL_CONTEXT_ORIGIN, ConversationArtifact, ConversationTurn, TurnLifecycle, TurnStatus,
)
from app.agentic.observation import TurnObservation
from app.agentic.presentation import (
    AcceptedArtifact,
    AssistantText,
    PresentedSession,
    PresentedTurn,
    ToolActivity,
    ToolStatus,
    UserPrompt,
    present_session,
)
from app.agentic.runner import AgentTurnRunner
from app.agentic.sessions import SessionSnapshot
from app.agentic.turns import create_turn_agent
from app.agentic.artifacts import ArtifactContent


NOW = datetime(2026, 10, 21, tzinfo=UTC)


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def turn(
    run_id: str | None, status: TurnStatus, observation: TurnObservation | None = None,
) -> ConversationTurn:
    return ConversationTurn(TurnLifecycle(
        run_id=run_id, status=status, started_at=NOW,
        finished_at=None if status == "running" else NOW,
    ), observation)


def snapshot(
    messages: Sequence[ModelMessage], *, status: TurnStatus = "completed",
    started: bool = False, artifacts: tuple[ConversationArtifact, ...] = (),
) -> SessionSnapshot:
    observation = TurnObservation()
    observation.messages = list(messages)
    observation.run_id = "run"
    if started:
        observation.started_tool_calls = (ToolCallPart("lookup", {}, "call"),)
    return SessionSnapshot(
        session_id="session", expires_at=NOW + timedelta(hours=1), artifacts=artifacts,
        turns=(turn("run", status, observation),), initial_context_message=None,
    )


def groups(snapshot: PresentedSession) -> tuple[PresentedTurn, ...]:
    return tuple(item for item in snapshot.history if isinstance(item, PresentedTurn))


def context_prompt(text: str) -> UserPromptPart:
    return UserPromptPart([TextContent(text, metadata={"origin": INITIAL_CONTEXT_ORIGIN})])


def test_serialized_contract_selects_only_display_data_and_preserves_native_order() -> None:
    artifact = ConversationArtifact(
        artifact_id="artifact", type="example", created_at=NOW, run_id="run",
        tool_call_id="call", content=ArtifactContent(title="Example", payload={"visible": [42]}),
    )
    internal = snapshot([
        ModelRequest(parts=[context_prompt("SECRET_CONTEXT")]),
        ModelRequest(parts=[SystemPromptPart("SECRET_INSTRUCTIONS"), UserPromptPart("Find it.")],
                     run_id="run", instructions="SECRET_DYNAMIC_INSTRUCTIONS"),
        ModelResponse(parts=[
            ThinkingPart("SECRET_REASONING", signature="SECRET_SIGNATURE"),
            TextPart("Looking up.", provider_name="openai", provider_details={
                "phase": "commentary", "annotations": [{"secret": "SECRET_ANNOTATIONS"}],
            }),
            ToolCallPart("lookup", {"secret": "SECRET_ARGUMENTS"}, "call"),
        ], run_id="run", provider_details={"secret": "SECRET_PROVIDER_DETAILS"}),
        ModelRequest(parts=[ToolReturnPart("lookup", "SECRET_RESULT", "call")], run_id="run"),
        ModelResponse(parts=[TextPart("Found it.")], run_id="run"),
    ], artifacts=(artifact,))
    projected = present_session(internal)
    assert [item.part_kind for item in projected.history] == ["user-prompt", "turn"]
    assert [part.part_kind for part in groups(projected)[0].parts] == [
        "text", "tool-call", "artifact", "text",
    ]
    activity = groups(projected)[0].parts[1]
    assert isinstance(activity, ToolActivity) and activity.status == "success"
    text = groups(projected)[0].parts[0]
    assert isinstance(text, AssistantText) and text.phase == "commentary"
    encoded = projected.model_dump_json()
    assert "turns" not in projected.model_dump()
    assert groups(projected)[0].lifecycle == internal.turns[0].lifecycle
    assert "SECRET" not in encoded
    assert "usage" not in encoded and "provider_details" not in encoded
    assert PresentedSession.model_validate_json(encoded) == projected
    displayed = groups(projected)[0].parts[2]
    assert isinstance(displayed, AcceptedArtifact)
    assert isinstance(displayed.artifact.content.payload, dict)
    displayed.artifact.content.payload["visible"] = "changed"
    assert artifact.content.payload == {"visible": [42]}
    assert groups(present_session(internal))[0].parts[2] != displayed


@pytest.mark.parametrize("outcome", ["success", "failed", "denied", "interrupted"])
def test_explicit_native_outcomes_override_live_activity(
    outcome: Literal["success", "failed", "denied", "interrupted"],
) -> None:
    internal = snapshot([
        ModelResponse(parts=[ToolCallPart("lookup", {}, "call")], run_id="run"),
        ModelRequest(parts=[ToolReturnPart(
            "lookup", "An error-looking result does not determine status.", "call", outcome=outcome,
        )], run_id="run"),
    ], status="running", started=True)
    activity = groups(present_session(internal))[0].parts[0]
    assert isinstance(activity, ToolActivity) and activity.status == outcome


@pytest.mark.parametrize(("status", "started", "expected"), [
    ("running", False, "requested"), ("running", True, "running"),
    ("failed", False, "interrupted"), ("failed", True, "interrupted"),
    ("cancelled", True, "interrupted"), ("completed", False, "interrupted"),
])
def test_unresolved_calls_never_claim_an_execution_outcome(
    status: TurnStatus, started: bool, expected: ToolStatus,
) -> None:
    internal = snapshot([
        ModelResponse(parts=[ToolCallPart("lookup", {}, "call")], run_id="run"),
    ], status=status, started=started)
    activity = groups(present_session(internal))[0].parts[0]
    assert isinstance(activity, ToolActivity) and activity.status == expected


def test_retry_failures_and_native_search_status_are_selected_without_exposing_results() -> None:
    internal = snapshot([
        ModelResponse(parts=[
            ToolCallPart("lookup", {}, "same"),
            NativeToolCallPart("web_search", {"query": "SECRET_QUERY"}, "same"),
        ], run_id="run"),
        ModelRequest(parts=[RetryPromptPart("SECRET_VALIDATION", tool_name="lookup", tool_call_id="same")]),
        ModelResponse(parts=[NativeToolReturnPart(
            "web_search", {"status": "failed", "secret": "SECRET_SEARCH"}, "same", provider_name="openai",
        )], run_id="run"),
    ])
    projected = present_session(internal)
    assert [(part.part_kind, part.status) for part in groups(projected)[0].parts
            if isinstance(part, ToolActivity)] == [("tool-call", "failed"), ("builtin-tool-call", "failed")]
    assert "SECRET" not in projected.model_dump_json()


@pytest.mark.parametrize(("provider_status", "expected"), [
    ("completed", "success"), ("failed", "failed"), ("in_progress", "interrupted"),
    ("searching", "interrupted"),
])
def test_openai_native_search_preserves_provider_completion_status(
    provider_status: str, expected: ToolStatus,
) -> None:
    internal = snapshot([ModelResponse(parts=[
        NativeToolCallPart("web_search", {}, "search"),
        NativeToolReturnPart("web_search", {"status": provider_status}, "search", provider_name="openai"),
    ], run_id="run")])
    activity = groups(present_session(internal))[0].parts[0]
    assert isinstance(activity, ToolActivity) and activity.status == expected


def test_cumulative_history_groups_old_turns_and_matches_reused_ids_by_call_order() -> None:
    internal = snapshot([
        ModelRequest(parts=[UserPromptPart("First")], run_id="first"),
        ModelResponse(parts=[ToolCallPart("lookup", {}, "reused")], run_id="first"),
        ModelRequest(parts=[ToolReturnPart("lookup", "secret", "reused", outcome="interrupted")]),
        ModelRequest(parts=[UserPromptPart("Second")], run_id="run"),
        ModelResponse(parts=[ToolCallPart("lookup", {}, "reused")], run_id="run"),
        ModelRequest(parts=[ToolReturnPart("lookup", 42, "reused")], run_id="run"),
        ModelResponse(parts=[TextPart("Done")], run_id="run"),
    ])
    internal = SessionSnapshot(
        session_id=internal.session_id, expires_at=internal.expires_at, artifacts=(),
        turns=(turn("first", "cancelled"), turn(None, "failed"), *internal.turns),
        initial_context_message=None,
    )
    projected = present_session(internal)
    empty = groups(projected)[1]
    assert empty.lifecycle.run_id is None and empty.lifecycle.status == "failed" and empty.parts == ()
    assert [item.content for item in projected.history if isinstance(item, UserPrompt)] == ["First", "Second"]
    first, _, second = groups(projected)
    assert first.lifecycle.run_id == "first" and second.lifecycle.run_id == "run"
    assert isinstance(first.parts[0], ToolActivity) and first.parts[0].status == "interrupted"
    assert isinstance(second.parts[0], ToolActivity) and second.parts[0].status == "success"


def test_admission_and_setup_failure_expose_lifecycle_without_context() -> None:
    internal = SessionSnapshot(
        session_id="session", expires_at=NOW, artifacts=(),
        turns=(turn(None, "failed"), turn(None, "running", TurnObservation())),
        initial_context_message=ModelRequest(parts=[UserPromptPart("SECRET_CONTEXT")]),
    )
    projected = present_session(internal)
    assert [item.lifecycle.status for item in groups(projected)] == ["failed", "running"]
    assert all(item.parts == () for item in groups(projected))
    assert len(projected.history) == 2
    assert "SECRET" not in projected.model_dump_json()
    assert PresentedSession.model_validate_json(projected.model_dump_json()) == projected


@pytest.mark.parametrize("pending_run_id", [None, "pending"])
def test_turn_without_response_follows_retained_history_and_carries_its_lifecycle(
    pending_run_id: str | None,
) -> None:
    internal = snapshot([
        ModelRequest(parts=[UserPromptPart("First")]),
        ModelResponse(parts=[TextPart("Done")], run_id="run"),
    ])
    pending = turn(pending_run_id, "running", TurnObservation())
    internal = SessionSnapshot(
        session_id=internal.session_id, expires_at=internal.expires_at, artifacts=(),
        turns=(*internal.turns, pending), initial_context_message=None,
    )
    projected = present_session(internal)
    assert [item.part_kind for item in projected.history] == ["user-prompt", "turn", "turn"]
    completed, admitted = groups(projected)
    assert completed.lifecycle.status == "completed" and completed.parts == (AssistantText(content="Done"),)
    assert admitted.lifecycle == pending.lifecycle and admitted.parts == ()
    assert PresentedSession.model_validate_json(projected.model_dump_json()) == projected


def test_native_request_merging_preserves_failed_prompts_without_exposing_context() -> None:
    history = repair_messages([
        ModelRequest(parts=[context_prompt("SECRET_CONTEXT")]),
        ModelRequest(parts=[UserPromptPart("First", timestamp=NOW)], run_id="first"),
        ModelRequest(parts=[UserPromptPart("Second", timestamp=NOW)], run_id="second"),
        ModelRequest(parts=[UserPromptPart("Third", timestamp=NOW)], run_id="run"),
        ModelResponse(parts=[TextPart("Done")], run_id="run"),
    ])
    history = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(history))
    assert len(history) == 2 and history[0].run_id is None
    observation = TurnObservation()
    observation.messages = history
    internal = SessionSnapshot(
        session_id="session", expires_at=NOW, artifacts=(), initial_context_message=None,
        turns=(turn("first", "failed"), turn("second", "failed"),
               turn("run", "completed", observation)),
    )
    projected = present_session(internal)
    assert [item.content for item in projected.history if isinstance(item, UserPrompt)] == ["First", "Second", "Third"]
    assert [item.part_kind for item in projected.history] == [
        "user-prompt", "user-prompt", "user-prompt", "turn", "turn", "turn",
    ]
    assert [item.lifecycle.status for item in groups(projected)] == ["failed", "failed", "completed"]
    assert [item.parts for item in groups(projected)[:2]] == [(), ()]
    assert "SECRET" not in projected.model_dump_json()


def test_prompt_visibility_uses_native_metadata_rather_than_text_or_run_attribution() -> None:
    internal = snapshot([ModelRequest(parts=[
        context_prompt("Initial application context: same text"),
        UserPromptPart("Initial application context: same text"),
        UserPromptPart([TextContent("First fragment"), "Second fragment"]),
    ])])
    projected = present_session(internal)
    assert projected.history[:2] == (
        UserPrompt(content="Initial application context: same text"),
        UserPrompt(content=("First fragment", "Second fragment")),
    )
    assert groups(projected) == (PresentedTurn(lifecycle=internal.turns[0].lifecycle, parts=()),)
    assert PresentedSession.model_validate_json(projected.model_dump_json()) == projected


def test_initial_context_stays_hidden_with_additional_metadata() -> None:
    internal = snapshot([ModelRequest(parts=[UserPromptPart([
        TextContent("SECRET_CONTEXT", metadata={
            "origin": INITIAL_CONTEXT_ORIGIN, "source": "application",
        }),
        TextContent("Visible input", metadata={"source": "user"}),
    ])])])

    projected = present_session(internal)

    assert projected.history[0] == UserPrompt(content=("Visible input",))
    assert "SECRET_CONTEXT" not in projected.model_dump_json()


def test_prompt_between_responses_keeps_native_order_without_rebuilding_turn_boundaries() -> None:
    internal = snapshot([
        ModelRequest(parts=[UserPromptPart("Start")]),
        ModelResponse(parts=[ToolCallPart("lookup", {}, "call")], run_id="run"),
        ModelRequest(parts=[UserPromptPart("Additional input")]),
        ModelRequest(parts=[ToolReturnPart("lookup", 42, "call")]),
        ModelResponse(parts=[TextPart("Done")], run_id="run"),
    ])
    projected = present_session(internal)
    assert [item.part_kind for item in projected.history] == ["user-prompt", "turn", "user-prompt", "turn"]
    first, second = groups(projected)
    assert first.lifecycle == second.lifecycle == internal.turns[0].lifecycle
    assert first.lifecycle.run_id == "run"
    assert isinstance(first.parts[0], ToolActivity) and first.parts[0].status == "success"
    assert second.parts == (AssistantText(content="Done"),)


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled"])
def test_accepted_artifact_is_visible_without_a_confirmed_tool_return(status: TurnStatus) -> None:
    artifact = ConversationArtifact(
        artifact_id="artifact", type="example", created_at=NOW, run_id="run",
        tool_call_id="publish", content=ArtifactContent(title="Accepted", payload={"value": 42}),
    )
    internal = snapshot([
        ModelResponse(parts=[ToolCallPart("present_artifact", {}, "publish")], run_id="run"),
    ], status=status, artifacts=(artifact,))
    projected = present_session(internal)
    assert [part.part_kind for part in groups(projected)[0].parts] == ["tool-call", "artifact"]
    accepted = groups(projected)[0].parts[1]
    assert isinstance(accepted, AcceptedArtifact)
    assert accepted.artifact.artifact_id == "artifact"
    assert accepted.artifact.content.payload == {"value": 42}
    assert projected == present_session(internal)


@pytest.mark.parametrize(("publication_order", "expected"), [
    ((2,), ["call:0", "call:1", "call:2", "artifact:2"]),
    ((2, 0, 1), ["call:0", "artifact:0", "call:1", "artifact:1", "call:2", "artifact:2"]),
])
def test_parallel_publications_stay_beside_their_calls_as_artifacts_arrive(
    publication_order: tuple[int, ...], expected: list[str],
) -> None:
    artifacts = tuple(ConversationArtifact(
        artifact_id=f"artifact:{call}", type="example", created_at=NOW, run_id="run",
        tool_call_id=f"call:{call}", content=ArtifactContent(title="Accepted", payload={"value": call}),
    ) for call in publication_order)
    internal = snapshot([
        ModelResponse(parts=[
            ToolCallPart("present_artifact", {}, f"call:{call}") for call in range(3)
        ], run_id="run"),
        ModelRequest(parts=[
            ToolReturnPart("present_artifact", "internal result", f"call:{call}")
            for call in reversed(range(3))
        ], run_id="run"),
    ], status="running", artifacts=artifacts)
    parts = groups(present_session(internal))[0].parts
    assert [part.tool_call_id if isinstance(part, ToolActivity) else part.artifact.artifact_id
            for part in parts if isinstance(part, (ToolActivity, AcceptedArtifact))] == expected
    assert all(part.status == "success" for part in parts if isinstance(part, ToolActivity))


def test_real_runner_projection_tracks_tool_cancellation_and_native_followup_repair() -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()

        async def lookup() -> int:
            """Look up a value."""
            started.set()
            await release.wait()
            raise asyncio.CancelledError()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts = [part.content for msg in messages
                       for part in msg.parts if isinstance(part, UserPromptPart)]
            if prompts[-1] == "Follow up":
                return ModelResponse(parts=[TextPart("Followed up.")])
            return ModelResponse(parts=[TextPart("Looking."), ToolCallPart("lookup", {}, "call")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(lookup)])
        runner = AgentTurnRunner(agent)
        session = runner.create_session(owner="alice", initial_context={"secret": "SECRET_CONTEXT"})
        async with agent, runner, aclosing(runner.observe_session(session.session_id, owner="alice")) as updates:
            assert (await anext(updates)).history == ()
            await runner.submit(session.session_id, owner="alice", prompt="Find it")
            await asyncio.wait_for(started.wait(), 5)
            running = runner.read_session(session.session_id, owner="alice")
            assert isinstance(running.history[0], UserPrompt)
            activity = groups(running)[0].parts[-1]
            assert isinstance(activity, ToolActivity) and activity.status == "running"
            release.set()
            async with asyncio.timeout(5):
                async for update in updates:
                    if groups(update) and groups(update)[-1].lifecycle.status == "cancelled":
                        break
            failed = update
            assert groups(failed)[0].lifecycle.status == "cancelled"
            activity = groups(failed)[0].parts[-1]
            assert isinstance(activity, ToolActivity) and activity.status == "interrupted"
            assert "SECRET" not in failed.model_dump_json()
            await runner.submit(session.session_id, owner="alice", prompt="Follow up")
            async with asyncio.timeout(5):
                async for update in updates:
                    if len(groups(update)) == 2 and groups(update)[-1].lifecycle.status == "completed":
                        break
            continued = update
            assert groups(continued)[0] == groups(failed)[0]
            assert [item.content for item in continued.history if isinstance(item, UserPrompt)] == ["Find it", "Follow up"]
            assert [part.content for part in groups(continued)[1].parts
                    if isinstance(part, AssistantText)] == ["Followed up."]
            assert "SECRET" not in continued.model_dump_json()

    asyncio.run(exercise())
