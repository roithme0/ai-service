import asyncio
import json

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ListToolsResult, Tool
from pydantic import SecretStr
from fastapi import FastAPI

from app.agents.wiring import configure_agents, get_configured_agents
from app.core.config import Settings
from app.main import AgentLifespan
from app.mcp_connection import MCPConnection
from app.sessions.text_sessions import TextSessionCreation
from app.agents.kochwiki import KochwikiSessionInput
from app.models.agentic_generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from test_recipe_improvement_session_http import valid_request


def configured_settings() -> Settings:
    return Settings.model_construct(
        openai_api_key=SecretStr("test-key"),
        kochwiki_openai_model="test-model",
        kochwiki_base_url="http://localhost/api",
        kochwiki_mcp_url="http://localhost/mcp/",
    )


def test_http_discovery_agent_isolation_invocation_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        requests: list[AgenticGenerationRequest] = []

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) == 1:
                    call = AgenticToolCall("hello", "kochwiki__hello_world", "{}")
                    return AgenticGenerationResponse(
                        ({"type": "function_call", "call_id": call.call_id,
                          "name": call.name, "arguments": call.arguments},), (call,), None,
                    )
                return AgenticGenerationResponse((), (), "Hello World received")

        def generator_factory(*, model: str, client: object) -> Generator:
            return Generator()

        monkeypatch.setattr("app.agents.wiring.OpenAIAgenticGenerator", generator_factory)
        server = MCPServer("Test", instructions="Server-owned domain guidance")

        @server.tool()
        def hello_world() -> dict[str, str]:
            return {"message": "Hello World"}

        app = server.streamable_http_app(
            streamable_http_path="/mcp/", stateless_http=True, json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
        )
        async with app.router.lifespan_context(app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://localhost",
        ) as http:
            def client_for_url(url: str, *, read_timeout_seconds: float) -> Client:
                assert url == "http://localhost/mcp/"
                return Client(streamable_http_client(url, http_client=http), read_timeout_seconds=read_timeout_seconds)

            monkeypatch.setattr("app.mcp_connection.Client", client_for_url)
            agents = configure_agents(configured_settings())
            assert agents.kochwiki.agent is not None
            assert agents.demo.mcp_connections == ()
            connection, = agents.kochwiki.mcp_connections
            assert connection.tools == ()
            await agents.start()
            try:
                assert agents.kochwiki.agent is not None
                assert connection.instructions == "Server-owned domain guidance"
                assert [tool.name for tool in connection.tools] == ["hello_world"]
                assert connection.tools[0].input_schema["type"] == "object"
                result = await connection.call_tool("hello_world", {})
                assert not result.is_error
                assert result.structured_content == {"message": "Hello World"}
                payload = valid_request()
                created = agents.kochwiki.agent.create(KochwikiSessionInput(payload["source"], payload["foodstuffs"]))
                assert isinstance(created, TextSessionCreation)
                agents.kochwiki.agent.append_user_message(created.session_id, "Call hello world")
                turn = await agents.kochwiki.agent.execute_turn(created.session_id)
                assert turn.kind == "completed"
                assert turn.text == "Hello World received"
                assert turn.artifacts == ()
                assert [tool["name"] for tool in requests[0].tools] == [
                    "register_recipe_proposal", "kochwiki__hello_world",
                ]
                assert "Server-owned domain guidance" in requests[0].instructions
                assert "hello_world -> kochwiki__hello_world" in requests[0].instructions
                output = requests[1].input_items[-1]
                assert output["call_id"] == "hello"
                assert isinstance(output["output"], str)
                assert json.loads(output["output"])["structuredContent"] == {"message": "Hello World"}
                assert agents.demo.agent is not None
                assert isinstance(agents.demo.agent.create(None), TextSessionCreation)
            finally:
                await agents.close()
            assert connection.instructions is None
            assert connection.tools == ()
            with pytest.raises(RuntimeError, match="not started"):
                await connection.call_tool("hello_world", {})
            await connection.close()

    asyncio.run(exercise())


def test_discovery_consumes_all_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    cursors: list[str | None] = []

    async def list_tools(self: Client, *, cursor: str | None = None) -> ListToolsResult:
        cursors.append(cursor)
        name = "first" if cursor is None else "second"
        return ListToolsResult(
            tools=[Tool(name=name, input_schema={"type": "object"})],
            next_cursor="page-two" if cursor is None else None,
        )

    async def exercise() -> None:
        server = MCPServer("Paged")

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            return Client(server, read_timeout_seconds=read_timeout_seconds)

        monkeypatch.setattr("app.mcp_connection.Client", client_for_url)
        monkeypatch.setattr(Client, "list_tools", list_tools)
        connection = MCPConnection("paged", "http://localhost/mcp/")
        await connection.start()
        try:
            assert [tool.name for tool in connection.tools] == ["first", "second"]
            assert cursors == [None, "page-two"]
        finally:
            await connection.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("fail_discovery", [False, True])
def test_connection_failure_disables_only_owning_agent(
    monkeypatch: pytest.MonkeyPatch, fail_discovery: bool,
) -> None:
    async def exercise() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(
            lambda request: httpx2.Response(503, request=request)
        )) as http:
            server = MCPServer("Unavailable discovery")

            def client_for_url(url: str, *, read_timeout_seconds: float) -> Client:
                return Client(
                    server if fail_discovery else streamable_http_client(url, http_client=http),
                    read_timeout_seconds=read_timeout_seconds,
                )

            async def broken_list(self: Client, *, cursor: str | None = None) -> ListToolsResult:
                raise RuntimeError("discovery failure")

            monkeypatch.setattr("app.mcp_connection.Client", client_for_url)
            if fail_discovery:
                monkeypatch.setattr(Client, "list_tools", broken_list)
            agents = configure_agents(configured_settings())
            assert agents.kochwiki.agent is not None
            connection, = agents.kochwiki.mcp_connections
            await agents.start()
            try:
                assert agents.kochwiki.agent is None
                assert agents.demo.agent is not None
                assert isinstance(agents.demo.agent.create(None), TextSessionCreation)
                assert connection.tools == ()
                assert connection.instructions is None
                with pytest.raises(RuntimeError, match="not started"):
                    await connection.call_tool("hello_world", {})
            finally:
                await agents.close()

    asyncio.run(exercise())


def test_application_lifespan_owns_connection_and_clears_agent_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        server = MCPServer("Lifecycle", instructions="Guidance")

        def client_for_url(_url: str, *, read_timeout_seconds: float) -> Client:
            return Client(server, read_timeout_seconds=read_timeout_seconds)

        monkeypatch.setattr("app.mcp_connection.Client", client_for_url)
        monkeypatch.setattr("app.agents.wiring.get_settings", configured_settings)
        get_configured_agents.cache_clear()
        async with AgentLifespan(FastAPI()):
            agents = get_configured_agents()
            assert agents.kochwiki.agent is not None
            connection, = agents.kochwiki.mcp_connections
            assert connection.instructions == "Guidance"
        assert connection.instructions is None
        assert get_configured_agents.cache_info().currsize == 0

    asyncio.run(exercise())
