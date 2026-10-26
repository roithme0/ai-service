import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr
from pydantic_ai import Conversation, Tool, UnexpectedModelBehavior, models
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    NativeToolCallPart,
    NativeToolReturnPart,
    TextPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from app.capabilities.conversations import turns
from app.capabilities.conversations.mcp import create_mcp_toolset
from app.capabilities.conversations.observation import TurnObservation
from app.capabilities.conversations.turns import (
    create_openai_model,
    create_turn_agent,
    execute_turn,
)


@asynccontextmanager
async def mocked_model(
    monkeypatch: pytest.MonkeyPatch,
    respond: Callable[[httpx2.Request], httpx2.Response],
) -> AsyncIterator[OpenAIResponsesModel]:
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:

        def provider(*, api_key: str) -> OpenAIProvider:
            assert api_key == "test"
            return OpenAIProvider(api_key=api_key, http_client=http)

        monkeypatch.setattr(turns, "OpenAIProvider", provider)
        monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
        yield create_openai_model("gpt-5.2", SecretStr("test"))


def search_item(identity: str, *, status: str = "completed") -> dict[str, object]:
    return {
        "type": "web_search_call",
        "id": identity,
        "status": status,
        "action": {
            "type": "search",
            "query": "sample value",
            "sources": [{"type": "url", "url": "https://example.com/value"}],
        },
    }


def answer_item() -> dict[str, object]:
    return {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [
            {
                "type": "output_text",
                "text": "The value is 42.",
                "annotations": [
                    {
                        "type": "url_citation",
                        "url": "https://example.com/value",
                        "title": "Sample value",
                        "start_index": 0,
                        "end_index": 16,
                    }
                ],
            }
        ],
    }


def response(
    output: list[dict[str, object]], *, identity: str = "resp_1"
) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": identity,
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.2",
            "status": "completed",
            "output": output,
            "error": None,
        },
    )


def test_search_coexists_with_local_and_mcp_tools_and_retains_serialized_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []
    calls: list[str] = []
    server = MCPServer("Domain")

    @server.tool()
    def lookup_value() -> int:
        """Retrieve the domain value."""
        calls.append("mcp")
        return 42

    def local_status() -> str:
        """Retrieve the local status."""
        calls.append("local")
        return "ready"

    def respond(request: httpx2.Request) -> httpx2.Response:
        body = cast(dict[str, object], json.loads(request.content))
        requests.append(body)
        if len(requests) == 1:
            return response(
                [
                    search_item("ws_1"),
                    {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "local-1",
                        "name": "local_status",
                        "arguments": "{}",
                        "status": "completed",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_2",
                        "call_id": "mcp-1",
                        "name": "lookup_value",
                        "arguments": "{}",
                        "status": "completed",
                    },
                ]
            )
        return response(
            (
                [search_item("ws_2"), answer_item()]
                if len(requests) == 2
                else [answer_item()]
            ),
            identity=f"resp_{len(requests)}",
        )

    async def exercise() -> None:
        app = server.streamable_http_app(
            streamable_http_path="/mcp/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
        )
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
            ) as mcp_http,
            mocked_model(monkeypatch, respond) as model,
        ):
            toolset = create_mcp_toolset(
                "http://localhost/mcp/", id="domain", http_client=mcp_http
            )
            agent = create_turn_agent(
                model,
                instructions="Help the user.",
                tools=[Tool(local_status)],
                toolsets=[toolset],
                web_search=True,
            )
            observation = TurnObservation()
            async with agent:
                first = await execute_turn(
                    agent,
                    "Find the value.",
                    observation=observation,
                    usage_limits=UsageLimits(request_limit=2, tool_calls_limit=2),
                )
            history = ModelMessagesTypeAdapter.validate_json(first.all_messages_json())
            followup_agent = create_turn_agent(
                model, instructions="Use retained context."
            )
            async with followup_agent:
                second = await execute_turn(
                    followup_agent,
                    "Repeat that.",
                    conversation=Conversation(messages=list(history)),
                )

        assert first.output == second.output == "The value is 42."
        assert first.usage.requests == 2
        assert first.usage.tool_calls == 2
        assert first.usage.details["web_search_requests"] == 2
        assert second.usage.tool_calls == 0
        assert second.usage.details.get("web_search_requests", 0) == 0
        assert {call.tool_call_id for call in observation.started_tool_calls} == {
            "local-1",
            "mcp-1",
        }
        parts = [part for message in observation.messages for part in message.parts]
        native_calls = [part for part in parts if isinstance(part, NativeToolCallPart)]
        assert [part.tool_call_id for part in native_calls] == ["ws_1", "ws_2"]
        native_returns = [
            part for part in parts if isinstance(part, NativeToolReturnPart)
        ]
        assert native_returns[0].content == {
            "status": "completed",
            "sources": [{"type": "url", "url": "https://example.com/value"}],
        }
        text = next(part for part in parts if isinstance(part, TextPart))
        assert text.provider_details is not None
        assert (
            text.provider_details["annotations"][0]["url"]
            == "https://example.com/value"
        )
        assert ModelMessagesTypeAdapter.dump_json(history) == first.all_messages_json()

    asyncio.run(exercise())
    assert sorted(calls) == ["local", "mcp"]
    assert len(requests) == 3
    for body in requests:
        assert body["stream"] is False
        assert body["store"] is False
        assert body["max_tool_calls"] == 16
        assert "web_search_call.action.sources" in cast(list[str], body["include"])
    for body in requests[:2]:
        tool_types = {
            tool["type"] for tool in cast(list[dict[str, object]], body["tools"])
        }
        assert tool_types == {"web_search", "function"}
    assert not requests[2].get("tools")
    for body in requests[1:]:
        inputs = cast(list[dict[str, object]], body["input"])
        retained = [item for item in inputs if item.get("type") == "web_search_call"]
        assert retained
        assert all(
            "sources" not in cast(dict[str, object], item["action"])
            for item in retained
        )
    inputs = cast(list[dict[str, object]], requests[2]["input"])
    assert [item["id"] for item in inputs if item.get("type") == "web_search_call"] == [
        "ws_1",
        "ws_2",
    ]


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_native_search_status_is_retained_without_local_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    requests = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return response([search_item("ws_1", status=status), answer_item()])

    async def exercise() -> None:
        async with mocked_model(monkeypatch, respond) as model:
            agent = create_turn_agent(model, instructions="Help.", web_search=True)
            observation = TurnObservation()
            async with agent:
                await execute_turn(agent, "Search.", observation=observation)
        parts = [part for message in observation.messages for part in message.parts]
        result = next(part for part in parts if isinstance(part, NativeToolReturnPart))
        assert result.content["status"] == status
        assert observation.started_tool_calls == ()

    asyncio.run(exercise())
    assert requests == 1


def test_search_remains_bounded_by_model_request_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    def local_status() -> str:
        """Retrieve the local status."""
        return "ready"

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return response(
            [
                search_item(f"ws_{requests}"),
                {
                    "type": "function_call",
                    "id": f"fc_{requests}",
                    "call_id": f"call-{requests}",
                    "name": "local_status",
                    "arguments": "{}",
                    "status": "completed",
                },
            ],
            identity=f"resp_{requests}",
        )

    async def exercise() -> None:
        async with mocked_model(monkeypatch, respond) as model:
            agent = create_turn_agent(
                model,
                instructions="Search.",
                tools=[Tool(local_status)],
                web_search=True,
            )
            observation = TurnObservation()
            async with agent:
                with pytest.raises(UsageLimitExceeded, match="request_limit"):
                    await execute_turn(
                        agent,
                        "Keep searching.",
                        observation=observation,
                        usage_limits=UsageLimits(request_limit=2, tool_calls_limit=2),
                    )
        assert observation.usage.requests == 2
        assert observation.usage.tool_calls == 2
        assert observation.usage.details["web_search_requests"] == 2
        assert (
            sum(
                isinstance(part, NativeToolReturnPart)
                for message in observation.messages
                for part in message.parts
            )
            == 2
        )

    asyncio.run(exercise())
    assert requests == 2


def test_search_without_answer_obeys_zero_validation_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return response([search_item("ws_1")])

    async def exercise() -> None:
        async with mocked_model(monkeypatch, respond) as model:
            agent = create_turn_agent(model, instructions="Search.", web_search=True)
            observation = TurnObservation()
            async with agent:
                with pytest.raises(
                    UnexpectedModelBehavior, match="maximum output retries"
                ):
                    await execute_turn(agent, "Search.", observation=observation)
        assert observation.started_tool_calls == ()
        assert (
            sum(
                isinstance(part, NativeToolReturnPart)
                for message in observation.messages
                for part in message.parts
            )
            == 1
        )

    asyncio.run(exercise())
    assert requests == 1


def test_later_provider_failure_preserves_confirmed_search_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    def local_status() -> str:
        """Retrieve the local status."""
        return "ready"

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            return response(
                [
                    search_item("ws_1"),
                    {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call-1",
                        "name": "local_status",
                        "arguments": "{}",
                        "status": "completed",
                    },
                ]
            )
        return httpx2.Response(
            503, json={"error": {"message": "Unavailable", "type": "server_error"}}
        )

    async def exercise() -> None:
        async with mocked_model(monkeypatch, respond) as model:
            agent = create_turn_agent(
                model,
                instructions="Search.",
                tools=[Tool(local_status)],
                web_search=True,
            )
            observation = TurnObservation()
            async with agent:
                with pytest.raises(ModelHTTPError, match="503"):
                    await execute_turn(agent, "Search.", observation=observation)
        assert (
            sum(
                isinstance(part, NativeToolReturnPart)
                for message in observation.messages
                for part in message.parts
            )
            == 1
        )
        assert [call.tool_call_id for call in observation.started_tool_calls] == [
            "call-1"
        ]

    asyncio.run(exercise())
    assert requests == 2
