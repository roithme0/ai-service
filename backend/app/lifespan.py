"""Application resource startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from mcp.server import MCPServer

from app.capabilities.conversations.lifecycle import kochwiki_runner
from app.capabilities.conversations.runner import AgentTurnRunner
from app.capabilities.embeddings.lifecycle import embedding_service
from app.capabilities.transcriptions.lifecycle import transcription_service
from app.core.config import get_provider_settings
from app.core.logging import configure_logging
from app.demos.live_conversation_demo.lifecycle import live_conversation_demo_runner
from app.demos.visual_conversation_demo.lifecycle import visual_conversation_demo_runner


@asynccontextmanager
async def application_lifespan(
    application: FastAPI, *, mcp_server: MCPServer
) -> AsyncIterator[None]:
    configure_logging()
    runners: dict[str, AgentTurnRunner | None] = {
        "kochwiki": None,
        "visual-demo": None,
        "live-demo": None,
    }
    application.state.agent_runners = runners
    resources = AsyncExitStack()
    try:
        await resources.enter_async_context(mcp_server.session_manager.run())
        mcp_http_client = await resources.enter_async_context(
            AsyncClient(transport=ASGITransport(app=application))
        )
        provider_settings = get_provider_settings()
        application.state.embedding_service = await resources.enter_async_context(
            embedding_service(provider_settings),
        )
        application.state.transcription_service = await resources.enter_async_context(
            transcription_service(provider_settings),
        )
        runners["kochwiki"] = await resources.enter_async_context(
            kochwiki_runner(provider_settings)
        )
        runners["visual-demo"] = await resources.enter_async_context(
            visual_conversation_demo_runner()
        )
        runners["live-demo"] = await resources.enter_async_context(
            live_conversation_demo_runner(
                provider_settings, mcp_http_client=mcp_http_client
            )
        )
        yield
    finally:
        runners["kochwiki"] = None
        runners["visual-demo"] = None
        runners["live-demo"] = None
        await resources.aclose()
