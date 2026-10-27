import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from app.capabilities.conversations.runner import AgentTurnRunner
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo.agent import create_live_conversation_demo_agent


@asynccontextmanager
async def live_conversation_demo_runner(
    provider_settings: ProviderSettings,
) -> AsyncIterator[AgentTurnRunner | None]:
    runner: AgentTurnRunner | None = None
    async with AsyncExitStack() as lifetime:
        try:
            async with AsyncExitStack() as startup:
                agent = await startup.enter_async_context(
                    create_live_conversation_demo_agent(provider_settings)
                )
                runner = await startup.enter_async_context(AgentTurnRunner(agent))
                lifetime.push_async_callback(startup.pop_all().aclose)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Live Demo agent unavailable during initialization (%s).",
                type(error).__name__,
            )
        yield runner
