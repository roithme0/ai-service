"""Application resource startup and shutdown."""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from app.capabilities.conversations.lifecycle import kochwiki_runner
from app.capabilities.conversations.runner import AgentTurnRunner
from app.capabilities.embeddings.lifecycle import embedding_service
from app.core.config import get_provider_settings
from app.core.logging import configure_logging
from app.demos.visual_conversation_demo.lifecycle import visual_conversation_demo_runner


@asynccontextmanager
async def application_lifespan(application: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    runners: dict[str, AgentTurnRunner | None] = {"kochwiki": None, "visual-demo": None}
    application.state.agent_runners = runners
    resources = AsyncExitStack()
    try:
        provider_settings = get_provider_settings()
        application.state.embedding_service = await resources.enter_async_context(
            embedding_service(provider_settings),
        )
        runners["kochwiki"] = await resources.enter_async_context(
            kochwiki_runner(provider_settings)
        )
        runners["visual-demo"] = await resources.enter_async_context(
            visual_conversation_demo_runner()
        )
        yield
    finally:
        runners["kochwiki"] = None
        runners["visual-demo"] = None
        await resources.aclose()
