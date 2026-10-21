"""Compose configured agents with MCP sessions owned by individual runs."""

from urllib.parse import urlparse

from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import DynamicToolset

from app.agentic.instructions import CONVERSATION_INSTRUCTIONS
from app.agentic.mcp import create_mcp_toolset
from app.agentic.turns import create_openai_model, create_turn_agent
from app.core.config import Settings


def create_kochwiki_agent(settings: Settings) -> Agent[None, str]:
    """Build the agent; the caller owns its native async context lifetime."""
    key = settings.openai_api_key
    model = settings.kochwiki_openai_model
    mcp_url = settings.kochwiki_mcp_url
    missing: list[str] = []
    if key is None or not key.get_secret_value().strip():
        missing.append("OPENAI_API_KEY")
    if model is None or not model.strip():
        missing.append("KOCHWIKI_OPENAI_MODEL")
    if mcp_url is None or not _valid_mcp_url(mcp_url):
        missing.append("KOCHWIKI_MCP_URL")
    if missing:
        raise ValueError(
            "Invalid or missing agent configuration: " + ", ".join(missing)
        )
    assert key is not None and model is not None and mcp_url is not None

    def kochwiki_tools(_ctx: RunContext[None]) -> MCPToolset[None]:
        return create_mcp_toolset(mcp_url, id="kochwiki")

    agent = create_turn_agent(
        create_openai_model(
            model,
            key,
            reasoning_effort=settings.kochwiki_openai_reasoning_effort,
        ),
        instructions=CONVERSATION_INSTRUCTIONS,
        toolsets=[DynamicToolset(kochwiki_tools, per_run_step=False, id="kochwiki")],
        web_search=True,
    )
    agent.name = "kochwiki"
    return agent


def _valid_mcp_url(value: str) -> bool:
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
