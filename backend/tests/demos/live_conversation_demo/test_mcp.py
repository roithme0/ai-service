import asyncio
import json

import httpx2
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.mcp import create_mcp_toolset
from app.capabilities.conversations.turns import execute_turn
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo.agent import create_live_conversation_demo_agent


def test_mounted_greetings_discovery_resource_and_tool_contracts(
    app: FastAPI, mcp_http_client: httpx2.AsyncClient
) -> None:
    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            async with create_mcp_toolset(
                "http://localhost/mcp/", id="greetings", http_client=mcp_http_client
            ) as toolset:
                tools = await toolset.client.list_tools()
                assert {tool.name for tool in tools} == {"greet", "farewell"}
                assert all(
                    tool.annotations is not None
                    and tool.annotations.read_only_hint is True
                    for tool in tools
                )
                resources = await toolset.list_resources()
                assert len(resources) == 1
                assert resources[0].uri == "greetings://catalog"
                content = await toolset.read_resource(resources[0])
                assert isinstance(content, str)
                catalog = json.loads(content)
                assert set(catalog["languages"]) == {"en", "de"}
                assert catalog["motto"] == "Every hello starts an adventure."
                for tool, language, expected in (
                    ("greet", "en", "Hello, Ada!"),
                    ("greet", "de", "Hallo, Ada!"),
                    ("farewell", "en", "Goodbye, Ada!"),
                    ("farewell", "de", "Auf Wiedersehen, Ada!"),
                ):
                    result = await toolset.client.call_tool(
                        tool, {"name": " Ada ", "language": language}
                    )
                    assert not result.is_error
                    assert result.structured_content == {
                        "message": expected,
                        "source": "greetings-mock",
                    }
                for tool in ("greet", "farewell"):
                    for name, language in ((" ", "en"), ("Ada", "fr")):
                        result = await toolset.client.call_tool(
                            tool,
                            {"name": name, "language": language},
                            raise_on_error=False,
                        )
                        assert result.is_error
                    recovered = await toolset.client.call_tool(
                        tool, {"name": "Ada", "language": "en"}
                    )
                    assert not recovered.is_error

    asyncio.run(exercise())


def test_live_agent_receives_mcp_guidance_resources_and_both_tool_results(
    app: FastAPI,
    mcp_http_client: httpx2.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    requests = 0

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal requests
        requests += 1
        assert info.instructions is not None
        assert "Consult greetings://catalog" in info.instructions
        assert {tool.name for tool in info.function_tools} == {
            "greetings__greet",
            "greetings__farewell",
            "greetings__get_mcp_resource",
        }
        assert any(
            isinstance(part, UserPromptPart)
            and isinstance(part.content, str)
            and "greetings://catalog" in part.content
            for message in messages
            for part in message.parts
        )
        if requests == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "greetings__get_mcp_resource",
                        {"uri": "greetings://catalog"},
                        "catalog",
                    ),
                    ToolCallPart(
                        "greetings__greet", {"name": "Ada", "language": "de"}, "hello"
                    ),
                    ToolCallPart(
                        "greetings__farewell", {"name": "Ada", "language": "en"}, "bye"
                    ),
                ]
            )
        results = {
            part.tool_call_id: part
            for message in messages
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        }
        assert results["hello"].outcome == results["bye"].outcome == "success"
        assert "Every hello starts an adventure." in str(results["catalog"].content)
        assert "Hallo, Ada!" in str(results["hello"].content)
        assert "Goodbye, Ada!" in str(results["bye"].content)
        return ModelResponse(parts=[TextPart("Greetings verified.")])

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            agent = create_live_conversation_demo_agent(
                ProviderSettings(_env_file=None, openai_api_key=SecretStr("test-key")),
                mcp_http_client=mcp_http_client,
            )
            async with agent:
                with agent.override(model=FunctionModel(respond)):
                    result = await execute_turn(agent, "Welcome Ada and say goodbye.")
                    assert result.output == "Greetings verified."
                    assert result.usage.tool_calls == 3

    asyncio.run(exercise())
    assert requests == 2
