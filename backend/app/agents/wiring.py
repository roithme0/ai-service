"""Construction, shared lifecycle, and cached access for configured agents."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from openai import AsyncOpenAI

from app.demo.agent import DemoAgent, create_demo_agent
from app.agents.model_agent import ModelAgent, create_model_agent
from app.agents.runtime import AgentRuntime
from app.core.config import Settings, get_settings
from app.agents.openai_agentic_generation import OpenAIAgenticGenerator
from app.mcp.connection import MCPConnection
from app.agents.models.web_search import WebSearchConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfiguredAgents:
    kochwiki: AgentRuntime[ModelAgent]
    demo: AgentRuntime[DemoAgent]

    async def start(self) -> None:
        await self.kochwiki.start()
        await self.demo.start()

    async def close(self) -> None:
        async with AsyncExitStack() as resources:
            resources.push_async_callback(self.kochwiki.close)
            resources.push_async_callback(self.demo.close)


def configure_kochwiki_agent(settings: Settings) -> AgentRuntime[ModelAgent]:
    missing: list[str] = []
    key = settings.openai_api_key
    model = settings.kochwiki_openai_model
    mcp_url = settings.kochwiki_mcp_url
    if key is None or not key.get_secret_value().strip():
        missing.append("OPENAI_API_KEY")
    if model is None or not model.strip():
        missing.append("KOCHWIKI_OPENAI_MODEL")
    if mcp_url is None or not _valid_http_url(mcp_url):
        missing.append("KOCHWIKI_MCP_URL")
    if missing:
        logger.warning(
            "Kochwiki agent unavailable: invalid or missing configuration: %s",
            ", ".join(missing),
        )
        return AgentRuntime("kochwiki", None)
    assert key is not None and model is not None and mcp_url is not None
    client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=0)
    runtime: AgentRuntime[ModelAgent] = AgentRuntime(
        "kochwiki",
        None,
        model_client=client,
        mcp_connections=(MCPConnection("kochwiki", mcp_url),),
    )
    runtime.agent = create_model_agent(
        OpenAIAgenticGenerator(
            model=model,
            client=client,
            reasoning_effort=settings.kochwiki_openai_reasoning_effort,
        ),
        tool_sources=(runtime.mcp_tools,),
        web_search=WebSearchConfig(),
    )
    return runtime


def configure_agents(settings: Settings) -> ConfiguredAgents:
    kochwiki = configure_kochwiki_agent(settings)
    demo = AgentRuntime("demo", create_demo_agent())
    return ConfiguredAgents(
        kochwiki=kochwiki,
        demo=demo,
    )


@lru_cache(maxsize=1)
def get_configured_agents() -> ConfiguredAgents:
    return configure_agents(get_settings())


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.port != 0
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False
