import asyncio
from unittest.mock import patch

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from openai.types.shared import ReasoningEffort
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import main
from app.core.identity import ApplicationIdentity
from app.agentic import wiring
from app.agentic.mcp import create_mcp_toolset
from app.agentic.presentation import PresentedTurn
from app.agentic.runner import AgentTurnRunner, RunnerClosedError
from app.core.config import Settings
from app.main import app
from tests.test_pydantic_http import stream

client = TestClient(app)


def test_application_http_errors_remain_typed_and_hide_internal_details() -> None:
    runner = AgentTurnRunner(Agent(FunctionModel(
        lambda messages, info: ModelResponse(parts=[TextPart("Unused")]),
    )))
    app.dependency_overrides[main.get_agent_registry] = lambda: {"kochwiki": runner}
    try:
        client = TestClient(app, raise_server_exceptions=False)
        base = "/api/v1/agents/kochwiki/sessions"
        method_error = client.put(base)
        assert method_error.status_code == 405
        assert method_error.json() == {"detail": "Method Not Allowed", "kind": "method_not_allowed"}
        assert "POST" in method_error.headers["allow"]
        missing = client.get("/missing")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found", "kind": "not_found"}
        with patch.object(AgentTurnRunner, "create_session", side_effect=RuntimeError("Private failure")) as create:
            invalid = client.post(base, json={}, headers={"X-Application-User": "invalid"})
            assert invalid.status_code == 422
            assert invalid.json()["kind"] == "request_validation"
            create.assert_not_called()
            unexpected = client.post(base, json={}, headers={"X-Application-User": "test:alice"})
            assert unexpected.status_code == 500
            assert unexpected.json() == {"detail": "Internal Server Error", "kind": "internal_error"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("failure", [ValueError("Invalid configuration"), RuntimeError("Initialization failed")])
def test_kochwiki_initialization_failure_does_not_block_application(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    def unavailable(settings: Settings) -> Agent[None, str]:
        raise failure

    monkeypatch.setattr(main, "create_kochwiki_agent", unavailable)
    with TestClient(app) as client:
        headers = {"X-Application-User": "test:user"}
        unavailable_response = client.post("/api/v1/agents/kochwiki/sessions", json={}, headers=headers)
        assert unavailable_response.status_code == 503
        assert unavailable_response.json() == {"kind": "agent_unavailable"}
        assert client.post("/api/v1/agents/demo/sessions", json={}, headers=headers).status_code == 201
        assert client.post("/api/native/api/v1/agents/demo/sessions", json={}, headers=headers).status_code == 404


def test_kochwiki_cutover_mcp_outage_recovery_and_resource_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    server = MCPServer("Kochwiki", instructions="Use lookup for recipe data.")
    calls: list[str] = []
    available = False
    lose_tool_response = False
    attempts = 0

    @server.tool()
    def lookup(name: str) -> dict[str, str]:
        """Look up a recipe."""
        calls.append(name)
        return {"name": name}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert info.instructions is not None and "Use lookup" in info.instructions
        assert {tool.name for tool in info.function_tools} == {"lookup"}
        last = messages[-1]
        if any(isinstance(part, ToolReturnPart) for part in last.parts) and not any(
            isinstance(part, UserPromptPart) for part in last.parts
        ):
            return ModelResponse(parts=[TextPart("Found soup.")])
        return ModelResponse(parts=[ToolCallPart("lookup", {"name": "Soup"})])

    async def exercise() -> None:
        nonlocal available, lose_tool_response
        mcp_app = server.streamable_http_app(
            streamable_http_path="/mcp/", stateless_http=True, json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
        )
        transport = httpx2.ASGITransport(app=mcp_app)

        async def send(request: httpx2.Request) -> httpx2.Response:
            nonlocal attempts
            attempts += 1
            if not available:
                raise httpx2.ConnectError("MCP unavailable", request=request)
            response = await transport.handle_async_request(request)
            if lose_tool_response and b'"tools/call"' in request.content:
                await response.aclose()
                raise httpx2.ReadError("Tool response lost", request=request)
            return response

        async with mcp_app.router.lifespan_context(mcp_app), httpx2.AsyncClient(
            transport=httpx2.MockTransport(send),
        ) as mcp_http:
            def mcp(url: str, *, id: str, identity: ApplicationIdentity) -> MCPToolset[None]:
                return create_mcp_toolset(url, id=id, http_client=mcp_http)

            def model(model_name: str, api_key: SecretStr, *, reasoning_effort: ReasoningEffort) -> FunctionModel:
                return FunctionModel(respond)

            monkeypatch.setattr(wiring, "create_mcp_toolset", mcp)
            monkeypatch.setattr(wiring, "create_openai_model", model)
            monkeypatch.setattr(main, "get_settings", lambda: Settings(
                _env_file=None, openai_api_key="test-key", kochwiki_openai_model="test",
                kochwiki_mcp_url="http://localhost/mcp/",
            ))
            async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://service",
                headers={"X-Application-User": "test:alice"},
            ) as client:
                assert attempts == 0
                runner: AgentTurnRunner = app.state.agent_runners["kochwiki"]
                creation = await client.post("/api/v1/agents/kochwiki/sessions", json={"initial_context": {"recipe": "Soup"}})
                assert creation.status_code == 201
                path = "/api/v1/agents/kochwiki/sessions/" + creation.json()["session_id"]
                assert (await client.post(f"{path}/messages", json={"text": "Old API"})).status_code == 404
                async with stream(app, f"{path}/events") as updates:
                    for ordinal, status in enumerate(("failed", "completed", "failed", "completed"), 1):
                        available = ordinal > 1
                        lose_tool_response = ordinal == 3
                        assert (await client.post(f"{path}/turns", json={"prompt": "Find soup"})).status_code == 202
                        snapshot = await updates.until(lambda value: (
                            len(turns := [item for item in value.history if isinstance(item, PresentedTurn)]) == ordinal
                            and turns[-1].lifecycle.status == status
                        ))
                        assert (await client.get(path)).json() == snapshot.model_dump(mode="json")
                assert calls == ["Soup", "Soup", "Soup"]
                assert (await client.get(path, headers={"X-Application-User": "test:other"})).status_code == 404
            with pytest.raises(RunnerClosedError):
                runner.create_session(owner=ApplicationIdentity("test", "alice"))

    asyncio.run(exercise())
