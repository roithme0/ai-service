import asyncio
import json

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ListToolsResult, Tool
from pydantic import SecretStr
from openai.types.shared import ReasoningEffort
from fastapi import FastAPI

from app.agents.wiring import configure_agents, get_configured_agents
from app.core.config import Settings
from app.main import AgentLifespan
from app.mcp.connection import MCPConnection
from app.agents.instructions import CONVERSATION_INSTRUCTIONS
from app.sessions.models.session import SessionCreation
from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse, AgenticToolCall
from test_model_session_http import valid_request


def configured_settings() -> Settings:
    return Settings.model_construct(
        openai_api_key=SecretStr("test-key"),
        kochwiki_openai_model="test-model",
        kochwiki_openai_reasoning_effort="high",
        kochwiki_mcp_url="http://localhost/mcp/",
    )


@pytest.mark.parametrize("with_presentation", [False, True])
def test_http_discovery_agent_isolation_invocation_and_shutdown(
    monkeypatch: pytest.MonkeyPatch, with_presentation: bool,
) -> None:
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
                return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "Hello World received"},), (), "Hello World received")

        def generator_factory(*, model: str, client: object, reasoning_effort: ReasoningEffort) -> Generator:
            assert reasoning_effort == "high"
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

            monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
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
                if with_presentation:
                    payload["artifactCapabilities"] = [{
                        "type": "test-card",
                        "description": "Display a complete test result.",
                        "titleDescription": "Use the result name as the title.",
                        "payloadSchema": {
                            "type": "object", "properties": {"name": {"type": "string"}},
                            "required": ["name"], "additionalProperties": False,
                        },
                    }]
                created = agents.kochwiki.agent.create(payload, owner="test:user")
                assert isinstance(created, SessionCreation)
                agents.kochwiki.agent.append_user_message(created.session_id, "Call hello world")
                turn = await agents.kochwiki.agent.execute_turn(created.session_id)
                assert turn.kind == "completed"
                assert turn.text == "Hello World received"
                assert turn.artifacts == ()
                assert [tool["name"] for tool in requests[0].tools if tool["type"] == "function"] == [
                    "kochwiki__hello_world",
                ] + (["present_artifact"] if with_presentation else [])
                assert {"type": "web_search"} in requests[0].tools
                assert requests[0].max_hosted_tool_calls == 16
                instructions = requests[0].instructions
                assert instructions.count("Server-owned domain guidance") == 1
                assert "hello_world -> kochwiki__hello_world" in instructions
                assert instructions.endswith(CONVERSATION_INSTRUCTIONS)
                if with_presentation:
                    assert "test-card" in instructions
                    assert "Use the result name as the title." in instructions
                    assert "Presentation does not create or save domain data." in instructions
                else:
                    assert "Available presentation capabilities" not in instructions
                assert requests[1].instructions == instructions
                output = requests[1].input_items[-1]
                assert output["call_id"] == "hello"
                assert isinstance(output["output"], str)
                assert json.loads(output["output"])["structuredContent"] == {"message": "Hello World"}
                assert agents.demo.agent is not None
                assert isinstance(agents.demo.agent.create(None, owner="test:user"), SessionCreation)
            finally:
                await agents.close()
            assert connection.instructions is None
            assert connection.tools == ()
            with pytest.raises(RuntimeError, match="not started"):
                await connection.call_tool("hello_world", {})
            await connection.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("save_fails", [False, True])
def test_configured_agent_creates_and_saves_mcp_proposal_across_turns(
    monkeypatch: pytest.MonkeyPatch, save_fails: bool,
) -> None:
    async def exercise() -> None:
        proposal_id = "dd6a58a5-b9b8-41fc-b13b-10ab5cf471be"
        version_id = "fa6a9a58-1bfa-4f4e-910a-9996c5f858b5"
        requests: list[AgenticGenerationRequest] = []
        created_proposals: list[dict[str, object]] = []
        saved_ids: list[str] = []
        payload = valid_request()
        source = payload["context"]["source"]
        assert isinstance(source, dict)
        candidate = {"sourceRecipeVersionId": source["external_reference"],
                     "recipe": {"name": "Adjusted oats"}}

        class Generator:
            async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse:
                requests.append(request)
                if len(requests) in (1, 3):
                    creating = len(requests) == 1
                    if not creating:
                        assert any(proposal_id in str(item.get("content", ""))
                                   for item in request.input_items if item.get("role") == "assistant")
                    call = AgenticToolCall(
                        "create" if creating else "save",
                        "kochwiki__create_recipe_proposal" if creating else "kochwiki__save_recipe_proposal",
                        json.dumps({"proposal": candidate} if creating else {"proposal_id": proposal_id}),
                    )
                    return AgenticGenerationResponse(({
                        "type": "function_call", "call_id": call.call_id,
                        "name": call.name, "arguments": call.arguments,
                    },), (call,), None)
                output = request.input_items[-1]["output"]
                assert isinstance(output, str)
                result = json.loads(output)
                if len(requests) == 2:
                    assert result["structuredContent"]["proposalId"] == proposal_id
                    return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": f"Proposal {proposal_id}: Adjusted oats."},), (), f"Proposal {proposal_id}: Adjusted oats.")
                if save_fails:
                    assert result["isError"] is True
                    return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": "Saving failed; no draft was saved."},), (), "Saving failed; no draft was saved.")
                assert result["structuredContent"]["id"] == version_id
                return AgenticGenerationResponse(({"type": "message", "role": "assistant", "phase": "final_answer", "content": f"Saved draft {version_id}."},), (), f"Saved draft {version_id}.")

        def generator_factory(*, model: str, client: object, reasoning_effort: ReasoningEffort) -> Generator:
            assert reasoning_effort == "high"
            return Generator()

        monkeypatch.setattr("app.agents.wiring.OpenAIAgenticGenerator", generator_factory)
        server = MCPServer("Proposals", instructions="Use create_recipe_proposal for proposals; save only on request.")

        @server.tool()
        def create_recipe_proposal(proposal: dict[str, object]) -> dict[str, object]:
            created_proposals.append(proposal)
            return {"proposalId": proposal_id, **proposal}

        @server.tool()
        def save_recipe_proposal(proposal_id: str) -> dict[str, str]:
            saved_ids.append(proposal_id)
            if save_fails:
                raise ToolError("Missing referenced foodstuff")
            return {"id": version_id, "name": "Adjusted oats"}

        app = server.streamable_http_app(
            streamable_http_path="/mcp/", stateless_http=True, json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
        )
        async with app.router.lifespan_context(app), httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://localhost",
        ) as http:
            def client_for_url(url: str, *, read_timeout_seconds: float) -> Client:
                return Client(streamable_http_client(url, http_client=http), read_timeout_seconds=read_timeout_seconds)

            monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
            agents = configure_agents(configured_settings())
            await agents.start()
            try:
                agent = agents.kochwiki.agent
                assert agent is not None
                created = agent.create(payload, owner="test:user")
                assert isinstance(created, SessionCreation)
                agent.append_user_message(created.session_id, "Propose a change")
                proposal_turn = await agent.execute_turn(created.session_id)
                assert proposal_turn.kind == "completed"
                assert proposal_turn.artifacts == ()
                assert saved_ids == []
                agent.append_user_message(created.session_id, "Save that proposal")
                save_turn = await agent.execute_turn(created.session_id)
                assert save_turn.kind == "completed"
                assert save_turn.artifacts == ()
                assert save_turn.text == ("Saving failed; no draft was saved." if save_fails
                                          else f"Saved draft {version_id}.")
                assert created_proposals == [candidate]
                assert saved_ids == [proposal_id]
                assert {tool["name"] for tool in requests[0].tools if tool["type"] == "function"} == {
                    "kochwiki__create_recipe_proposal", "kochwiki__save_recipe_proposal",
                }
                assert "register_recipe_proposal" not in requests[0].instructions
                assert "inline temporary definitions" not in requests[0].instructions
                snapshot = json.loads(str(requests[0].input_items[0]["content"]).split("\n", 1)[1])
                assert set(snapshot) == {"source", "foodstuffs"}
                assert snapshot["source"]["external_reference"] == source["external_reference"]
                assert snapshot["source"]["recipe"]["ingredients"][0]["amount"] == 125.75
                assert snapshot["foodstuffs"][0]["name"] == "Oats"
                read = agent.read(created.session_id)
                assert read.kind == "active"
            finally:
                await agents.close()

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

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
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

            monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
            if fail_discovery:
                monkeypatch.setattr(Client, "list_tools", broken_list)
            agents = configure_agents(configured_settings())
            assert agents.kochwiki.agent is not None
            connection, = agents.kochwiki.mcp_connections
            await agents.start()
            try:
                assert agents.kochwiki.agent is None
                assert agents.demo.agent is not None
                assert isinstance(agents.demo.agent.create(None, owner="test:user"), SessionCreation)
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

        monkeypatch.setattr("app.mcp.connection.Client", client_for_url)
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
