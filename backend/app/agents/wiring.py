"""Process lifetime and availability for configured agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from openai import AsyncOpenAI

from app.agents.demo import DemoAgent, create_demo_agent
from app.agents.recipe import RecipeAgent, create_recipe_agent
from app.core.config import Settings, get_settings
from app.models.openai_agentic_generation import OpenAIAgenticGenerator
from app.recipe_improvement.resolver import KochwikiRecipePresentationResolver


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfiguredAgents:
    recipe: RecipeAgent | None
    demo: DemoAgent
    model_client: AsyncOpenAI | None = None

    async def close(self) -> None:
        if self.model_client is not None:
            await self.model_client.close()


def configure_agents(settings: Settings) -> ConfiguredAgents:
    demo = create_demo_agent()
    missing: list[str] = []
    key = settings.openai_api_key
    model = settings.recipe_improvement_openai_model
    base_url = settings.kochwiki_base_url
    if key is None or not key.get_secret_value().strip():
        missing.append("OPENAI_API_KEY")
    if model is None or not model.strip():
        missing.append("RECIPE_IMPROVEMENT_OPENAI_MODEL")
    if base_url is None or not _valid_resolver_url(base_url):
        missing.append("KOCHWIKI_BASE_URL")
    if missing:
        logger.warning("Recipe agent unavailable: invalid or missing configuration: %s", ", ".join(missing))
        return ConfiguredAgents(None, demo)
    assert key is not None and model is not None and base_url is not None
    client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=0)
    recipe = create_recipe_agent(
        OpenAIAgenticGenerator(model=model, client=client),
        KochwikiRecipePresentationResolver(base_url),
    )
    return ConfiguredAgents(recipe, demo, client)


@lru_cache(maxsize=1)
def get_configured_agents() -> ConfiguredAgents:
    return configure_agents(get_settings())


def _valid_resolver_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme in ("http", "https") and bool(parsed.hostname)
            and parsed.port != 0 and not parsed.username and not parsed.password
        )
    except ValueError:
        return False
