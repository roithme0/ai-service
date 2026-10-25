import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from app.capabilities.agentic.config import get_kochwiki_conversation_settings
from app.capabilities.agentic.runner import AgentTurnRunner
from app.capabilities.agentic.wiring import create_kochwiki_agent
from app.core.config import ProviderSettings


@asynccontextmanager
async def kochwiki_runner(provider_settings: ProviderSettings) -> AsyncIterator[AgentTurnRunner | None]:
    runner: AgentTurnRunner | None = None
    async with AsyncExitStack() as lifetime:
        try:
            async with AsyncExitStack() as startup:
                agent = await startup.enter_async_context(create_kochwiki_agent(
                    get_kochwiki_conversation_settings(), provider_settings=provider_settings,
                ))
                runner = await startup.enter_async_context(AgentTurnRunner(agent))
                lifetime.push_async_callback(startup.pop_all().aclose)
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Kochwiki agent unavailable during initialization (%s).", type(error).__name__,
            )
        yield runner
