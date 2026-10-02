import asyncio
from datetime import timedelta
from typing import Never

import pytest

from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from app.sessions.conversation import ConversationReadActive, ConversationSessionSettings, ConversationSessionStore
from app.sessions.model_turns import ModelTurnStrategy
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_or_cancelled_model_turn_releases_session_without_replay(cancel: bool) -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        requests: list[AgenticGenerationRequest] = []

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if request.input_items[-1]["content"] == "first":
                    entered.set()
                    await release.wait()
                    raise RuntimeError("provider failure")
                return AgenticGenerationResponse((), (), "Reply")

        store = ConversationSessionStore[str, Never](timedelta(minutes=90))
        strategy = ModelTurnStrategy(store, Generator(), lambda context: context, ())
        first = store.create("Snapshot", ConversationSessionSettings(20))
        second = store.create("Independent", ConversationSessionSettings(20))
        store.append_user_message(first.session_id, "first")
        store.append_user_message(second.session_id, "second")
        task = asyncio.create_task(strategy(first.session_id))
        await entered.wait()
        assert (await strategy(first.session_id)).kind == "busy"
        assert (await strategy(second.session_id)).kind == "completed"
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            assert (await task).kind == "generation_failed"
        count = len(requests)
        assert (await strategy(first.session_id)).kind == "generation_failed"
        assert len(requests) == count
        read = store.read(first.session_id)
        assert isinstance(read, ConversationReadActive)
        assert read.snapshot.artifacts == ()
        assert [message.text for message in read.snapshot.session.messages] == ["first"]
        assert store.append_user_message(first.session_id, "recover").kind == "accepted"
        assert (await strategy(first.session_id)).kind == "completed"

    asyncio.run(exercise())


@pytest.mark.parametrize("provider_budget", [2, 8])
def test_artifact_free_turn_enforces_attempt_and_provider_budgets(provider_budget: int) -> None:
    async def exercise() -> None:
        requests: list[AgenticGenerationRequest] = []
        invocations: list[ToolInvocation] = []

        def execute(call: ToolInvocation) -> ToolExecution[Never]:
            invocations.append(call)
            return ToolExecution("Succeeded")

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) == 8:
                    assert "limit_reached" in str(request.input_items[-1]["output"])
                    return AgenticGenerationResponse((), (), "Finished")
                call = AgenticToolCall(str(len(requests)), "sample", "{}")
                return AgenticGenerationResponse(({
                    "type": "function_call", "call_id": call.call_id,
                    "name": call.name, "arguments": call.arguments,
                },), (call,), None)

        store = ConversationSessionStore[str, Never](timedelta(minutes=90))
        strategy = ModelTurnStrategy(
            store, Generator(), lambda context: context,
            (LocalToolSource((RegisteredTool("sample", {"type": "function", "name": "sample"}, execute),)),),
            max_provider_responses=provider_budget,
        )
        created = store.create("Snapshot", ConversationSessionSettings(20))
        store.append_user_message(created.session_id, "Run")
        result = await strategy(created.session_id)
        assert result.kind == ("generation_failed" if provider_budget == 2 else "completed")
        assert result.artifacts == ()
        assert len(requests) == provider_budget
        assert len(invocations) == min(provider_budget, 6)
        read = store.read(created.session_id)
        assert isinstance(read, ConversationReadActive)
        assert len(read.snapshot.session.messages) == (1 if provider_budget == 2 else 2)

    asyncio.run(exercise())
