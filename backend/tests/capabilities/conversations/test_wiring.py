import asyncio

import httpx2
import pytest
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic_ai import models
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.native_tools import WebSearchTool

from app.capabilities.conversations import wiring
from app.capabilities.conversations.identity import bind_turn_identity
from app.core.identity import ApplicationIdentity
from app.capabilities.conversations.artifacts import (
    ArtifactAccepted,
    ArtifactCapability,
)
from app.capabilities.conversations.session_state import SessionState
from app.capabilities.conversations.mcp import create_mcp_toolset
from app.core.config import ProviderSettings
from app.capabilities.conversations.config import KochwikiConversationSettings


@pytest.fixture(autouse=True)
def prevent_live_model_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


def settings(**changes: object) -> KochwikiConversationSettings:
    values: dict[str, object] = {
        "kochwiki_openai_model": "gpt-5.2",
        "kochwiki_openai_reasoning_effort": "low",
        "kochwiki_mcp_url": "http://localhost/mcp/",
    }
    values.update(changes)
    return KochwikiConversationSettings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("field", "value", "name"),
    [
        ("openai_api_key", None, "OPENAI_API_KEY"),
        ("openai_api_key", "  ", "OPENAI_API_KEY"),
        ("kochwiki_openai_model", None, "KOCHWIKI_OPENAI_MODEL"),
        ("kochwiki_openai_model", "  ", "KOCHWIKI_OPENAI_MODEL"),
        ("kochwiki_mcp_url", None, "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "  ", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "ftp://localhost/mcp", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "http:///mcp", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "http://localhost:0/mcp", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "http://localhost:bad/mcp", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "http://user:password@localhost/mcp", "KOCHWIKI_MCP_URL"),
        ("kochwiki_mcp_url", "http://[broken/mcp", "KOCHWIKI_MCP_URL"),
    ],
)
def test_invalid_settings_fail_before_constructing_resources(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    name: str,
) -> None:
    def unexpected_model(
        model_name: str,
        api_key: object,
        *,
        reasoning_effort: object,
    ) -> OpenAIResponsesModel:
        pytest.fail("Invalid configuration must fail before creating resources")

    monkeypatch.setattr(wiring, "create_openai_model", unexpected_model)
    with pytest.raises(ValueError) as failure:
        conversation = (
            settings() if field == "openai_api_key" else settings(**{field: value})
        )
        provider = ProviderSettings(
            _env_file=None,
            **{
                "openai_api_key": value if field == "openai_api_key" else "test-key",
            },
        )
        wiring.create_kochwiki_agent(conversation, provider_settings=provider)
    assert str(failure.value) == "Invalid or missing agent configuration: " + name
    assert "test-key" not in str(failure.value)
    assert "password" not in str(failure.value)


def test_configured_agent_composes_mcp_artifacts_history_and_native_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MCPServer("Kochwiki", instructions="Use lookup_recipe for recipe data.")
    lookups: list[str] = []
    first = SessionState(
        artifact_capabilities=[
            ArtifactCapability(
                type="json",
                description="Show recipe data.",
                payloadSchema={"type": "object"},
            )
        ]
    )
    toolsets: list[MCPToolset[None]] = []

    @server.tool()
    def lookup_recipe(name: str) -> dict[str, str]:
        """Find a recipe by name."""
        lookups.append(name)
        return {"name": name}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts = [
            part.content
            for msg in messages
            for part in msg.parts
            if isinstance(part, UserPromptPart)
        ]
        results = [
            part
            for msg in messages
            for part in msg.parts
            if isinstance(part, ToolReturnPart)
        ]
        names = {tool.name for tool in info.function_tools}
        assert info.instructions is not None
        assert "Use lookup_recipe for recipe data." in info.instructions
        assert "Treat caller-provided context" in info.instructions
        assert any(
            isinstance(tool, WebSearchTool)
            for tool in info.model_request_parameters.native_tools
        )
        if prompts == ["Find and present soup."]:
            assert names == {
                "kochwiki__lookup_recipe",
                "present_artifact",
                "kochwiki__get_mcp_resource",
            }
            if not results:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "kochwiki__lookup_recipe", {"name": "Soup"}, "lookup-1"
                        )
                    ]
                )
            if len(results) == 1:
                assert results[0].content == {"name": "Soup"}
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "present_artifact",
                            {
                                "type": "json",
                                "content": {
                                    "title": "Soup",
                                    "payload": {"name": "Soup"},
                                },
                            },
                            "present-1",
                        )
                    ]
                )
            assert len(first.artifacts) == 1
            assert results[-1].content == ArtifactAccepted(
                artifact_id=first.artifacts[0].artifact_id
            )
        else:
            if prompts == ["Find and present soup.", "Repeat that."]:
                assert names == {
                    "kochwiki__lookup_recipe",
                    "present_artifact",
                    "kochwiki__get_mcp_resource",
                }
                assert len(results) == 2
            else:
                assert names == {
                    "kochwiki__lookup_recipe",
                    "kochwiki__get_mcp_resource",
                }
                assert prompts == ["Hello."]
                assert results == []
        return ModelResponse(parts=[TextPart("Soup is ready.")])

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
            ) as http,
        ):

            def mcp(
                url: str, *, id: str, identity: ApplicationIdentity
            ) -> MCPToolset[None]:
                assert url == "http://localhost/mcp/"
                assert id == "kochwiki"
                assert identity == ApplicationIdentity("test", "alice")
                toolset = create_mcp_toolset(url, id=id, http_client=http)
                toolsets.append(toolset)
                return toolset

            monkeypatch.setattr(wiring, "create_mcp_toolset", mcp)
            agent = wiring.create_kochwiki_agent(
                settings(),
                provider_settings=ProviderSettings(
                    _env_file=None, openai_api_key="test-key"
                ),
            )
            assert agent.name == "kochwiki"
            model = agent.model
            assert isinstance(model, OpenAIResponsesModel)
            assert model.model_name == "gpt-5.2"
            assert model.settings is not None
            assert model.settings["openai_reasoning_effort"] == "low"
            assert model.settings["openai_store"] is False
            assert model.client.api_key == "test-key"
            assert toolsets == []
            independent = SessionState()
            async with agent:
                assert toolsets == []
                assert not model.client.is_closed()
                with (
                    bind_turn_identity(ApplicationIdentity("test", "alice")),
                    agent.override(model=FunctionModel(respond)),
                ):
                    result = await first.execute_turn(agent, "Find and present soup.")
                    followup = await first.execute_turn(agent, "Repeat that.")
                    separate = await independent.execute_turn(agent, "Hello.")
                assert (
                    result.output
                    == followup.output
                    == separate.output
                    == "Soup is ready."
                )
                assert result.usage.tool_calls == 2
                assert followup.usage.tool_calls == result.usage.tool_calls
                assert separate.usage.tool_calls == 0
            assert model.client.is_closed()
            assert len(toolsets) == 3
            assert all(not toolset.client.is_connected() for toolset in toolsets)
            assert not http.is_closed
            assert len(first.artifacts) == 1
            assert first.artifacts[0].tool_call_id == "present-1"
            assert first.artifacts[0].run_id == result.run_id
            assert independent.artifacts == ()
            assert (
                first.conversation.conversation_id
                != independent.conversation.conversation_id
            )
        assert http.is_closed

    asyncio.run(exercise())
    assert lookups == ["Soup"]


def test_configured_mcp_failure_is_confined_to_each_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    toolsets: list[MCPToolset[None]] = []

    def unavailable(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        raise httpx2.ConnectError("MCP unavailable", request=request)

    async def exercise() -> None:
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(unavailable)
        ) as http:

            def mcp(
                url: str, *, id: str, identity: ApplicationIdentity
            ) -> MCPToolset[None]:
                assert identity == ApplicationIdentity("test", "alice")
                toolset = create_mcp_toolset(url, id=id, http_client=http)
                toolsets.append(toolset)
                return toolset

            monkeypatch.setattr(wiring, "create_mcp_toolset", mcp)
            agent = wiring.create_kochwiki_agent(
                settings(),
                provider_settings=ProviderSettings(
                    _env_file=None, openai_api_key="test-key"
                ),
            )
            async with agent:
                assert attempts == 0
                with (
                    bind_turn_identity(ApplicationIdentity("test", "alice")),
                    agent.override(
                        model=FunctionModel(
                            lambda messages, info: ModelResponse(
                                parts=[TextPart("Hello")]
                            )
                        )
                    ),
                ):
                    session_state = SessionState()
                    for prompt in ("First", "Try again"):
                        with pytest.raises(
                            RuntimeError,
                            match="Client failed to connect: MCP unavailable",
                        ):
                            await session_state.execute_turn(agent, prompt)
                assert len(session_state.turn_executions) == 2
                assert all(
                    execution.lifecycle.status == "failed"
                    for execution in session_state.turn_executions
                )
            assert all(not toolset.client.is_connected() for toolset in toolsets)
            assert not http.is_closed

    asyncio.run(exercise())
    assert attempts == 2


@pytest.mark.parametrize("effort", [None, "none", "high"])
def test_configured_metadata_matches_requests_and_lifecycle(
    effort: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from contextlib import aclosing
    from typing import cast

    from pydantic_ai.capabilities import Caching
    from pydantic_ai.providers.openai import OpenAIProvider

    from app.capabilities.conversations import turns
    from app.capabilities.conversations.presentation import PresentedTurn
    from app.capabilities.conversations.runner import AgentTurnRunner

    async def exercise() -> None:
        requests: list[dict[str, object]] = []
        started, release = asyncio.Event(), asyncio.Event()

        async def respond(request: httpx2.Request) -> httpx2.Response:
            requests.append(cast(dict[str, object], json.loads(request.content)))
            started.set()
            await release.wait()
            if len(requests) == 2:
                return httpx2.Response(400, json={"error": {"message": "failed"}})
            return httpx2.Response(
                200,
                json={
                    "id": "resp_1",
                    "object": "response",
                    "created_at": 1,
                    "model": "configured-model",
                    "status": "completed",
                    "error": None,
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Done",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                },
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:

            def provider(*, api_key: str) -> OpenAIProvider:
                return OpenAIProvider(api_key=api_key, http_client=http)

            monkeypatch.setattr(turns, "OpenAIProvider", provider)
            monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
            monkeypatch.setattr(
                wiring, "MCPResources", lambda *args, **kwargs: Caching()
            )
            agent = wiring.create_kochwiki_agent(
                settings(
                    kochwiki_openai_model="configured-model",
                    kochwiki_openai_reasoning_effort=effort,
                ),
                provider_settings=ProviderSettings(
                    _env_file=None, openai_api_key="test-key"
                ),
            )
            runner = AgentTurnRunner(agent)
            owner = ApplicationIdentity("test", "alice")
            created = runner.create_session(owner=owner)
            expected = {"name": "configured-model", "reasoning_effort": effort}

            def check_model(snapshot: object) -> None:
                from app.capabilities.conversations.presentation import PresentedSession

                assert isinstance(snapshot, PresentedSession)
                assert snapshot.model is not None
                assert snapshot.model.model_dump() == expected

            async with (
                agent,
                runner,
                aclosing(
                    runner.observe_session(created.session_id, owner=owner)
                ) as updates,
            ):
                check_model(runner.read_session(created.session_id, owner=owner))
                check_model(await anext(updates))
                for outcome in ("completed", "failed"):
                    started.clear()
                    release.clear()
                    await runner.submit(created.session_id, owner=owner, prompt="Hello")
                    await asyncio.wait_for(started.wait(), 5)
                    running = runner.read_session(created.session_id, owner=owner)
                    assert isinstance(running.history[-1], PresentedTurn)
                    assert running.history[-1].lifecycle.status == "running"
                    check_model(running)
                    check_model(await anext(updates))
                    release.set()
                    async with asyncio.timeout(5):
                        async for snapshot in updates:
                            check_model(snapshot)
                            if (
                                isinstance(snapshot.history[-1], PresentedTurn)
                                and snapshot.history[-1].lifecycle.status == outcome
                            ):
                                break
                    check_model(runner.read_session(created.session_id, owner=owner))
            assert len(requests) == 2
            for request in requests:
                assert request["model"] == expected["name"]
                reasoning = request.get("reasoning")
                assert reasoning == ({"effort": effort} if effort is not None else None)

    asyncio.run(exercise())
