import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import Agent, Tool, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextContent, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.core.identity import ApplicationIdentity
from app.capabilities.conversations.session_state import SessionState, SessionBusyError, TurnExecution
from app.capabilities.conversations.presentation import AcceptedArtifact, AssistantText, PresentedSession, PresentedTurn, ToolActivity, UserPrompt
from app.capabilities.conversations.runner import AgentTurnRunner, RunnerClosedError
from app.capabilities.conversations.sessions import AgentSessionRegistry, SessionNotFoundError
from app.capabilities.conversations.turns import create_turn_agent
from app.capabilities.conversations.artifacts import ArtifactCapability
from app.core.json import FiniteJsonValue


def groups(snapshot: PresentedSession) -> tuple[PresentedTurn, ...]:
    return tuple(item for item in snapshot.history if isinstance(item, PresentedTurn))


def artifacts(snapshot: PresentedSession) -> tuple[AcceptedArtifact, ...]:
    return tuple(part for group in groups(snapshot) for part in group.parts
                 if isinstance(part, AcceptedArtifact))


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


async def wait_until_settled(runner: AgentTurnRunner, session_id: str) -> None:
    async with asyncio.timeout(5):
        while groups(runner.read_session(session_id, owner=ApplicationIdentity("test", "alice")))[-1].lifecycle.status == "running":
            await asyncio.sleep(0)


def test_submission_waits_for_admission_and_survives_submitting_caller_cancellation() -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        submission_returned = asyncio.Event()

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts = [part.content for message in messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            assert "rejected" not in prompts
            started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Finished.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"))
        async with agent, runner:
            async def submit() -> None:
                await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="work")
                snapshot = runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))
                assert len(groups(snapshot)) == 1
                assert groups(snapshot)[0].lifecycle.status == "running"
                with pytest.raises(SessionBusyError):
                    await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="rejected")
                submission_returned.set()
                await asyncio.Event().wait()

            caller = asyncio.create_task(submit())
            await asyncio.wait_for(started.wait(), 5)
            await asyncio.wait_for(submission_returned.wait(), 5)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[0].lifecycle.status == "running"
            release.set()
            await wait_until_settled(runner, created.session_id)
            assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[0].lifecycle.status == "completed"
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="followup")
            await wait_until_settled(runner, created.session_id)
            assert len(groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))) == 2
        with pytest.raises(RunnerClosedError):
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="rejected")

    asyncio.run(exercise())


def test_background_failure_is_consumed_and_later_turn_can_run(caplog: pytest.LogCaptureFixture) -> None:
    async def exercise() -> None:

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts = [part.content for message in messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            if prompts[-1] == "fail":
                raise RuntimeError("Sensitive provider payload")
            return ModelResponse(parts=[TextPart("Recovered.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"))
        async with agent, runner:
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="fail")
            await wait_until_settled(runner, created.session_id)
            assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[0].lifecycle.status == "failed"
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="followup")
            await wait_until_settled(runner, created.session_id)
        assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[-1].lifecycle.status == "completed"

    asyncio.run(exercise())
    assert "Background agent turn failed (RuntimeError)." in caplog.text
    assert "Sensitive provider payload" not in caplog.text


def test_shutdown_before_execution_starts_cancels_submission_without_admission() -> None:
    async def exercise() -> None:
        calls = 0

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"), initial_context={"recipe": 42})
        async with agent:
            submission = asyncio.create_task(runner.submit(
                created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="never started",
            ))
            await asyncio.sleep(0)
            await runner.close()
            with pytest.raises(asyncio.CancelledError):
                await submission
            await runner.close()
            snapshot = runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))
            assert snapshot.history == ()
            assert calls == 0
            with pytest.raises(RunnerClosedError):
                async with runner:
                    pytest.fail("Closed runner was reopened")
            with pytest.raises(RunnerClosedError):
                runner.create_session(owner=ApplicationIdentity("test", "alice"))

    asyncio.run(exercise())


def test_caller_cancellation_before_admission_leaves_no_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        waiting = asyncio.Event()

        class DelayedSessions(AgentSessionRegistry):
            async def execute_turn(
                self,
                session_id: str,
                *,
                owner: ApplicationIdentity,
                agent: Agent[None, str],
                prompt: str,
                usage_limits: UsageLimits | None = None,
                toolsets: Sequence[AbstractToolset[None]] = (),
                on_admitted: Callable[[], None] | None = None,
            ) -> AgentRunResult[str]:
                waiting.set()
                await asyncio.Event().wait()
                return await super().execute_turn(
                    session_id, owner=owner, agent=agent, prompt=prompt,
                    usage_limits=usage_limits, toolsets=toolsets, on_admitted=on_admitted,
                )

        monkeypatch.setattr("app.capabilities.conversations.runner.AgentSessionRegistry", DelayedSessions)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            pytest.fail("Cancelled submission reached the model")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"))
        async with agent, runner:
            submission = asyncio.create_task(runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="work"))
            await asyncio.wait_for(waiting.wait(), 5)
            submission.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submission
        assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))) == ()

    asyncio.run(exercise())


def test_caller_cancellation_after_admission_before_submit_returns_keeps_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        started, release = asyncio.Event(), asyncio.Event()
        submission: asyncio.Task[None] | None = None
        admit_execution = SessionState._admit_execution

        def admit_and_cancel_caller(session_state: SessionState) -> TurnExecution:
            execution = admit_execution(session_state)
            assert submission is not None and not submission.done()
            submission.cancel()
            return execution

        monkeypatch.setattr(SessionState, "_admit_execution", admit_and_cancel_caller)

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"))
        async with agent, runner:
            submission = asyncio.create_task(runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="work"))
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(submission, 5)
            await asyncio.wait_for(started.wait(), 5)
            assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[0].lifecycle.status == "running"
            release.set()
            await wait_until_settled(runner, created.session_id)
            assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[0].lifecycle.status == "completed"

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_close", [0, 1, 2])
def test_shutdown_awaits_tool_cleanup_and_retains_artifacts(cancel_close: int) -> None:
    async def exercise() -> None:
        started, cleaning, release_cleanup, cleaned = (asyncio.Event() for _ in range(4))

        async def operation() -> str:
            """Perform a domain operation."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release_cleanup.wait()
                cleaned.set()
            return "Done"

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[
                ToolCallPart("present_artifact", {
                    "type": "example", "content": {"title": "Accepted", "payload": {}},
                }, "artifact"),
                ToolCallPart("operation", {}, "operation"),
            ])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.", tools=[Tool(operation)])
        runner = AgentTurnRunner(agent)
        created = runner.create_session(owner=ApplicationIdentity("test", "alice"), artifact_capabilities=[ArtifactCapability(
            type="example", description="Present data.", payloadSchema={"type": "object"},
        )])
        async with agent:
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="work")
            await asyncio.wait_for(started.wait(), 5)
            assert len(artifacts(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))) == 1
            closing = asyncio.create_task(runner.close())
            await asyncio.wait_for(cleaning.wait(), 5)
            assert not closing.done() and not cleaned.is_set()
            with pytest.raises(RunnerClosedError):
                await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="rejected")
            for _ in range(cancel_close):
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done()
            release_cleanup.set()
            if cancel_close:
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(closing, 5)
            else:
                await asyncio.wait_for(closing, 5)
            assert cleaned.is_set()
            snapshot = runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))
            assert groups(snapshot)[-1].lifecycle.status == "cancelled"
            assert any(isinstance(part, ToolActivity) and part.tool_name == "operation" and part.status == "interrupted"
                       for group in groups(snapshot) for part in group.parts)
            assert len(artifacts(snapshot)) == 1
            await runner.close()

    asyncio.run(exercise())


def test_owner_expiry_and_independent_session_admission() -> None:
    async def exercise() -> None:
        now = datetime(2026, 10, 20, tzinfo=UTC)
        both_started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            nonlocal calls
            calls += 1
            if calls == 2:
                both_started.set()
            await release.wait()
            return ModelResponse(parts=[TextPart("Done.")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent, clock=lambda: now)
        first = runner.create_session(owner=ApplicationIdentity("test", "alice"))
        second = runner.create_session(owner=ApplicationIdentity("test", "bob"))
        async with agent, runner:
            for session_id in (first.session_id, "missing"):
                with pytest.raises(SessionNotFoundError):
                    await runner.submit(session_id, owner=ApplicationIdentity("test", "bob"), prompt="denied")
            assert groups(runner.read_session(first.session_id, owner=ApplicationIdentity("test", "alice"))) == ()
            await runner.submit(first.session_id, owner=ApplicationIdentity("test", "alice"), prompt="work")
            await runner.submit(second.session_id, owner=ApplicationIdentity("test", "bob"), prompt="work")
            await asyncio.wait_for(both_started.wait(), 5)
            now += timedelta(minutes=90)
            with pytest.raises(SessionNotFoundError):
                await runner.submit(first.session_id, owner=ApplicationIdentity("test", "alice"), prompt="expired")
            release.set()
            await asyncio.sleep(0)
        assert calls == 2

    asyncio.run(exercise())


def test_runner_session_boundary_preserves_context_capacity_isolation_and_expiry() -> None:
    async def exercise() -> None:
        now = datetime(2026, 10, 20, tzinfo=UTC)
        context: dict[str, FiniteJsonValue] = {"recipe": 42}
        capability = ArtifactCapability(
            type="example", description="Present data.", payloadSchema={"type": "object"},
        )

        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            prompts = [part.content for message in messages for part in message.parts
                       if isinstance(part, UserPromptPart)]
            assert len(prompts) == 2 and not isinstance(prompts[0], str)
            assert isinstance(prompts[0][0], TextContent) and '"recipe":42' in prompts[0][0].content
            returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
            if returns:
                assert returns[-1].outcome == "failed"
                assert isinstance(returns[-1].content, str) and '"artifact_limit"' in returns[-1].content
                return ModelResponse(parts=[TextPart("No publication capacity.")])
            return ModelResponse(parts=[ToolCallPart("present_artifact", {
                "type": "example", "content": {"title": "Example", "payload": {}},
            }, "artifact")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        other_agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        runner = AgentTurnRunner(agent, session_lifetime=timedelta(minutes=3), clock=lambda: now)
        other_runner = AgentTurnRunner(other_agent, clock=lambda: now)
        created = runner.create_session(
            owner=ApplicationIdentity("test", "alice"), initial_context=context, artifact_capabilities=[capability], max_artifacts=0,
        )
        assert created.expires_at == now + timedelta(minutes=3)
        context["recipe"] = 99
        capability.payload_schema["type"] = "array"
        for reader, owner in ((runner, ApplicationIdentity("test", "bob")), (other_runner, ApplicationIdentity("test", "alice"))):
            with pytest.raises(SessionNotFoundError):
                reader.read_session(created.session_id, owner=owner)
        with pytest.raises(SessionNotFoundError):
            runner.read_session("missing", owner=ApplicationIdentity("test", "alice"))

        async with agent, other_agent, runner, other_runner:
            await runner.submit(created.session_id, owner=ApplicationIdentity("test", "alice"), prompt="present")
            await wait_until_settled(runner, created.session_id)
            snapshot = runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))
            assert groups(snapshot)[-1].lifecycle.status == "completed" and artifacts(snapshot) == ()
            assert snapshot.history[0] == UserPrompt(content="present")
            assert groups(snapshot)[-1].parts[-1] == AssistantText(content="No publication capacity.")
            assert PresentedSession.model_validate_json(snapshot.model_dump_json()) == snapshot

        assert groups(runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice")))[-1].lifecycle.status == "completed"
        with pytest.raises(RunnerClosedError):
            runner.create_session(owner=ApplicationIdentity("test", "alice"))
        now = created.expires_at
        with pytest.raises(SessionNotFoundError):
            runner.read_session(created.session_id, owner=ApplicationIdentity("test", "alice"))

    asyncio.run(exercise())
