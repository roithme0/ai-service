import asyncio
from contextlib import aclosing
from contextvars import ContextVar

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastmcp.client.transports import http as mcp_http
from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from starlette.requests import Request

from app.capabilities.conversations.http import create_session_router
from app.capabilities.conversations.identity import current_turn_identity
from app.capabilities.conversations.presentation import PresentedTurn
from app.capabilities.conversations.runner import AgentTurnRunner
from app.capabilities.conversations.sessions import AgentSessionRegistry
from app.capabilities.conversations.turns import create_turn_agent
from app.capabilities.conversations.wiring import create_kochwiki_agent
from app.core.config import ProviderSettings
from app.capabilities.conversations.config import KochwikiConversationSettings
from app.core.identity import ApplicationIdentity


@pytest.mark.parametrize(
    "header,identity,canonical",
    [
        ("%74est:%61lice", ApplicationIdentity("test", "alice"), "test:alice"),
        (
            "https%3a%2f%2fIDP.example%3a443%2frealm:cook%3a%C3%A4%20!'()*%25",
            ApplicationIdentity("https://IDP.example:443/realm", "cook:ä !'()*%"),
            "https%3A%2F%2FIDP.example%3A443%2Frealm:cook%3A%C3%A4%20!'()*%25",
        ),
        (
            "test:double%253Aencoded",
            ApplicationIdentity("test", "double%3Aencoded"),
            "test:double%253Aencoded",
        ),
    ],
)
def test_identity_decodes_once_and_encodes_like_encode_uri_component(
    header: str,
    identity: ApplicationIdentity,
    canonical: str,
) -> None:
    assert ApplicationIdentity.from_header(header) == identity
    assert identity.to_header() == canonical


@pytest.mark.parametrize(
    "header", ["", "a", ":b", "a:", "a:b:c", "a:b c", "a:%ZZ", "a:%FF", "a:b,c"]
)
def test_invalid_identity_assertions_are_rejected(header: str) -> None:
    with pytest.raises(ValueError):
        ApplicationIdentity.from_header(header)


@pytest.mark.parametrize("issuer,subject", [("", "alice"), ("test", "")])
def test_identity_components_must_not_be_empty(issuer: str, subject: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ApplicationIdentity(issuer, subject)


def test_http_ownership_uses_decoded_pair_and_rejects_duplicate_assertions() -> None:
    async def exercise() -> None:
        agent = create_turn_agent(
            FunctionModel(
                lambda messages, info: ModelResponse(parts=[TextPart("Done.")])
            ),
            instructions="Help.",
        )
        runner = AgentTurnRunner(agent)
        app = FastAPI()
        app.include_router(create_session_router(lambda: {"test": runner}))
        base = "/api/v1/agents/test/sessions"
        async with (
            agent,
            runner,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client,
        ):
            created = await client.post(
                base, json={}, headers={"X-Application-User": "%74est:%61lice"}
            )
            assert created.status_code == 201
            path = f"{base}/{created.json()['session_id']}"
            for method, suffix, body in (
                ("GET", "", None),
                ("POST", "/turns", {"prompt": "Hello"}),
                ("GET", "/events", None),
            ):
                for identity in ("other:alice", "test:bob"):
                    response = await client.request(
                        method,
                        path + suffix,
                        json=body,
                        headers={"X-Application-User": identity},
                    )
                    assert response.status_code == 404
                duplicate = await client.request(
                    method,
                    path + suffix,
                    json=body,
                    headers=[
                        ("X-Application-User", "test:alice"),
                        ("X-Application-User", "test:alice"),
                    ],
                )
                assert duplicate.status_code == 422
            assert (
                await client.get(path, headers={"X-Application-User": "test:alice"})
            ).status_code == 200
            accepted = await client.post(
                path + "/turns",
                json={"prompt": "Hello"},
                headers={"X-Application-User": "test:alice"},
            )
            assert accepted.status_code == 202
            async with aclosing(
                runner.observe_session(
                    created.json()["session_id"],
                    owner=ApplicationIdentity("test", "alice"),
                )
            ) as updates:
                snapshot = await anext(updates)
                assert snapshot.session_id == created.json()["session_id"]
            for invalid in ("test:%FF", "test:%ZZ"):
                response = await client.post(
                    base, json={}, headers={"X-Application-User": invalid}
                )
                assert response.status_code == 422

    asyncio.run(exercise())


def test_background_turns_forward_isolated_assertions_on_actual_mcp_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    async def exercise() -> None:
        server = MCPServer("Kochwiki")
        requests: list[str] = []
        calls: list[tuple[str, str]] = []
        clients: list[httpx2.AsyncClient] = []
        entered, release = asyncio.Event(), asyncio.Event()
        asserted_identity: ContextVar[str] = ContextVar("server_asserted_identity")

        async def capture(
            ctx: ServerRequestContext[object, object], call_next: CallNext
        ) -> HandlerResult:
            assert isinstance(ctx.request, Request)
            assertions = ctx.request.headers.getlist("X-Application-User")
            assert len(assertions) == 1
            requests.append(assertions[0])
            token = asserted_identity.set(assertions[0])
            try:
                return await call_next(ctx)
            finally:
                asserted_identity.reset(token)

        server.middleware.append(capture)

        @server.tool()
        async def caller_identity() -> str:
            """Return the identity retained across a concurrent tool invocation."""
            before = asserted_identity.get()
            calls.append((before, "entered"))
            if len(calls) == 2:
                entered.set()
            await release.wait()
            after = asserted_identity.get()
            assert before == after
            return after

        mcp_app = server.streamable_http_app(
            streamable_http_path="/mcp/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(allowed_hosts=["localhost"]),
        )

        def http_client(
            headers: dict[str, str] | None = None,
            timeout: httpx2.Timeout | None = None,
            auth: httpx2.Auth | None = None,
        ) -> httpx2.AsyncClient:
            client = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=mcp_app),
                headers=headers,
                timeout=timeout,
                auth=auth,
            )
            clients.append(client)
            return client

        monkeypatch.setattr(mcp_http, "create_mcp_http_client", http_client)

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returns = [
                part
                for message in messages
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            if not returns:
                return ModelResponse(
                    parts=[ToolCallPart("caller_identity", {}, "identity")]
                )
            return ModelResponse(parts=[TextPart(str(returns[-1].content))])

        agent = create_kochwiki_agent(
            KochwikiConversationSettings(
                _env_file=None,
                kochwiki_openai_model="gpt-5.2",
                kochwiki_mcp_url="http://localhost/mcp/",
            ),
            provider_settings=ProviderSettings(_env_file=None, openai_api_key="test"),
        )
        runner = AgentTurnRunner(agent)
        app = FastAPI()
        app.include_router(create_session_router(lambda: {"kochwiki": runner}))
        base = "/api/v1/agents/kochwiki/sessions"
        owners = (
            ApplicationIdentity("https://idp.example/one", "cook:ä !'()*%"),
            ApplicationIdentity("https://idp.example/two", "cook:ä !'()*%"),
        )
        async with (
            mcp_app.router.lifespan_context(mcp_app),
            agent,
            runner,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://test",
            ) as browser,
        ):
            with agent.override(model=FunctionModel(respond)):
                sessions: list[str] = []
                for owner in owners:
                    created = await browser.post(
                        base, json={}, headers={"X-Application-User": owner.to_header()}
                    )
                    assert created.status_code == 201
                    sessions.append(created.json()["session_id"])
                responses = await asyncio.gather(
                    *(
                        browser.post(
                            f"{base}/{session_id}/turns",
                            json={"prompt": "Who am I?"},
                            headers={"X-Application-User": owner.to_header()},
                        )
                        for owner, session_id in zip(owners, sessions, strict=True)
                    )
                )
                assert all(response.status_code == 202 for response in responses)
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    assert {identity for identity, _ in calls} == {
                        owner.to_header() for owner in owners
                    }
                finally:
                    release.set()
                for owner, session_id in zip(owners, sessions, strict=True):
                    async with aclosing(
                        runner.observe_session(session_id, owner=owner)
                    ) as updates:
                        async with asyncio.timeout(5):
                            async for snapshot in updates:
                                turns = [
                                    item
                                    for item in snapshot.history
                                    if isinstance(item, PresentedTurn)
                                ]
                                if turns and turns[-1].lifecycle.status != "running":
                                    assert turns[-1].lifecycle.status == "completed"
                                    assert (
                                        owner.to_header() in snapshot.model_dump_json()
                                    )
                                    break
        assert clients and all(client.is_closed for client in clients)
        assert set(requests) == {owner.to_header() for owner in owners}
        with pytest.raises(LookupError):
            current_turn_identity()

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel", [False, True])
def test_turn_identity_is_reset_after_failure_or_cancellation(cancel: bool) -> None:
    async def exercise() -> None:
        owner = ApplicationIdentity("test", "alice")

        async def respond(
            messages: list[ModelMessage], info: AgentInfo
        ) -> ModelResponse:
            assert current_turn_identity() == owner
            if cancel:
                raise asyncio.CancelledError
            raise RuntimeError("Failure")

        agent = create_turn_agent(FunctionModel(respond), instructions="Help.")
        registry = AgentSessionRegistry()
        session = registry.create(owner=owner)
        async with agent:
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await registry.execute_turn(
                    session.session_id, owner=owner, agent=agent, prompt="Hello"
                )
            with pytest.raises(LookupError):
                current_turn_identity()

    asyncio.run(exercise())
