import asyncio
import json
from typing import cast

import httpx2
import pytest
from pydantic import SecretStr
from pydantic_ai import Conversation, Tool, ToolFailed, UnexpectedModelBehavior, capture_run_messages
from pydantic_ai import models
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from app.capabilities.agentic import turns
from app.capabilities.agentic.turns import create_openai_model, create_turn_agent, execute_turn


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def test_tool_result_and_serialized_history_continue_without_reexecuting_tool() -> None:
    calls: list[str] = []
    requests = 0

    def lookup_value(label: str) -> int:
        """Look up a value by label."""
        calls.append(label)
        return 42

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert info.instructions == "Use the lookup tool."
        assert info.model_settings is not None
        assert info.model_settings["max_retries"] == 0
        assert info.model_settings["request_timeout"] == 120
        if requests == 1:
            assert [tool.name for tool in info.function_tools] == ["lookup_value"]
            return ModelResponse(parts=[ToolCallPart("lookup_value", {"label": "sample"}, "call-1")])
        results = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        assert len(results) == 1
        assert results[0].tool_call_id == "call-1"
        assert results[0].content == 42
        if requests == 3:
            assert isinstance(messages[-1].parts[-1], UserPromptPart)
            assert messages[-1].parts[-1].content == "Repeat the value."
        return ModelResponse(parts=[TextPart("The value is 42.")])

    async def exercise() -> None:
        agent = create_turn_agent(
            FunctionModel(respond),
            instructions="Use the lookup tool.",
            tools=[Tool(lookup_value)],
        )
        async with agent:
            first = await execute_turn(agent, "Find the sample value.")
            history = ModelMessagesTypeAdapter.validate_json(first.all_messages_json())
            second = await execute_turn(agent, "Repeat the value.", conversation=Conversation(messages=list(history)))
        assert first.output == second.output == "The value is 42."
        assert first.usage.requests == 2
        assert first.usage.tool_calls == 1
        assert second.usage.requests == 1
        assert second.usage.tool_calls == 0
        assert len(second.all_messages()) > len(history)
        assert not any(isinstance(part, ToolCallPart) for message in second.new_messages() for part in message.parts)

    asyncio.run(exercise())
    assert calls == ["sample"]
    assert requests == 3


def test_explicit_tool_failure_is_available_to_model_without_automatic_reexecution() -> None:
    calls = 0

    def lookup_value() -> str:
        """Look up the requested value."""
        nonlocal calls
        calls += 1
        raise ToolFailed("Value is unavailable.")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls == 0:
            return ModelResponse(parts=[ToolCallPart("lookup_value", {}, "call-1")])
        result = messages[-1].parts[0]
        assert isinstance(result, ToolReturnPart)
        assert result.outcome == "failed"
        assert "Value is unavailable." in str(result.content)
        return ModelResponse(parts=[TextPart("I could not retrieve the value.")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Look up the value.", tools=[Tool(lookup_value)])
        async with agent:
            result = await execute_turn(agent, "Find the value.")
        assert result.output == "I could not retrieve the value."

    asyncio.run(exercise())
    assert calls == 1


def test_unexpected_tool_exception_propagates_and_native_history_is_inspectable() -> None:
    calls = 0

    def lookup_value() -> str:
        """Look up the requested value."""
        nonlocal calls
        calls += 1
        raise RuntimeError("Unexpected tool failure")

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("lookup_value", {}, "call-1")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Look up the value.", tools=[Tool(lookup_value)])
        async with agent:
            with capture_run_messages() as history:
                with pytest.raises(RuntimeError, match="Unexpected tool failure"):
                    await execute_turn(agent, "Find the value.")
            assert any(isinstance(part, ToolCallPart) for message in history for part in message.parts)

    asyncio.run(exercise())
    assert calls == 1


@pytest.mark.parametrize("limit", ["requests", "tools"])
def test_repeated_tool_requests_stop_at_native_execution_limits(limit: str) -> None:
    calls = 0
    requests = 0

    def lookup_value() -> str:
        """Look up the requested value."""
        nonlocal calls
        calls += 1
        return "Found"

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[ToolCallPart("lookup_value", {}, f"call-{requests}")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Look up the value.", tools=[Tool(lookup_value)])
        limits = UsageLimits(request_limit=2, tool_calls_limit=10) if limit == "requests" else UsageLimits(
            request_limit=10, tool_calls_limit=1,
        )
        async with agent:
            with pytest.raises(UsageLimitExceeded):
                await execute_turn(agent, "Keep looking.", usage_limits=limits)

    asyncio.run(exercise())
    assert requests == 2
    assert calls == (2 if limit == "requests" else 1)


def test_invalid_tool_arguments_do_not_execute_or_retry() -> None:
    calls = 0
    requests = 0

    def lookup_value(label: str) -> str:
        """Look up a value by label."""
        nonlocal calls
        calls += 1
        return label

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        return ModelResponse(parts=[ToolCallPart("lookup_value", {}, "call-1")])

    async def exercise() -> None:
        agent = create_turn_agent(FunctionModel(respond), instructions="Look up the value.", tools=[Tool(lookup_value)])
        async with agent:
            with pytest.raises(UnexpectedModelBehavior):
                await execute_turn(agent, "Find the value.")

    asyncio.run(exercise())
    assert calls == 0
    assert requests == 1


def test_cancellation_reaches_the_running_tool() -> None:
    async def exercise() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def lookup_value() -> str:
            """Look up the requested value."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return "Unreachable"

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[ToolCallPart("lookup_value", {}, "call-1")])

        agent = create_turn_agent(FunctionModel(respond), instructions="Look up the value.", tools=[Tool(lookup_value)])
        async with agent:
            task = asyncio.create_task(execute_turn(agent, "Find the value."))
            await asyncio.wait_for(started.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cancelled.is_set()

    asyncio.run(exercise())


def test_openai_responses_round_trip_uses_native_provider_and_explicit_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/responses"
        requests.append(cast(dict[str, object], json.loads(request.content)))
        output: list[dict[str, object]] = [{
            "type": "function_call", "id": "fc_1", "call_id": "call-1",
            "name": "lookup_value", "arguments": '{"label":"sample"}', "status": "completed",
        }] if len(requests) == 1 else [{
            "type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": "The value is 42.", "annotations": []}],
        }]
        return httpx2.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "model": "gpt-5.2", "status": "completed", "output": output, "error": None,
        })

    def lookup_value(label: str) -> int:
        """Look up a value by label."""
        assert label == "sample"
        return 42

    async def exercise() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http_client:
            def provider(*, api_key: str) -> OpenAIProvider:
                assert api_key == "test"
                return OpenAIProvider(api_key=api_key, http_client=http_client)

            monkeypatch.setattr(turns, "OpenAIProvider", provider)
            monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
            agent = create_turn_agent(
                create_openai_model("gpt-5.2", SecretStr("test"), reasoning_effort="low"),
                instructions="Look up the value.",
                tools=[Tool(lookup_value)],
            )
            async with agent:
                result = await execute_turn(agent, "Find the sample value.")
            assert result.output == "The value is 42."
            assert result.usage.requests == 2
            assert result.usage.tool_calls == 1

    asyncio.run(exercise())
    assert len(requests) == 2
    for request in requests:
        assert request["store"] is False
        assert request["max_output_tokens"] == 16_384
        assert request["reasoning"] == {"effort": "low"}
    model_input = requests[1]["input"]
    assert isinstance(model_input, list)
    assert any(item.get("type") == "function_call_output" and item["output"] == "42" for item in model_input)
