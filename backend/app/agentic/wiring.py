"""Compose configured agents with MCP sessions owned by individual runs."""

from urllib.parse import urlparse

from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.toolsets import DynamicToolset

from app.agentic.instructions import CONVERSATION_INSTRUCTIONS
from app.agentic.identity import current_turn_identity
from app.agentic.mcp import create_mcp_toolset
from app.agentic.turns import create_openai_model, create_turn_agent
from app.core.config import Settings


def create_kochwiki_agent(settings: Settings) -> Agent[None, str]:
    """Build the agent; the caller owns its native async context lifetime."""
    api_key = settings.openai_api_key
    model_name = settings.kochwiki_openai_model
    mcp_url = settings.kochwiki_mcp_url
    invalid_settings: list[str] = []
    if api_key is None or not api_key.get_secret_value().strip():
        invalid_settings.append("OPENAI_API_KEY")
    if model_name is None or not model_name.strip():
        invalid_settings.append("KOCHWIKI_OPENAI_MODEL")
    if mcp_url is None or not _is_valid_mcp_url(mcp_url):
        invalid_settings.append("KOCHWIKI_MCP_URL")
    if invalid_settings:
        raise ValueError(
            "Invalid or missing agent configuration: " + ", ".join(invalid_settings)
        )
    assert api_key is not None and model_name is not None and mcp_url is not None

    def create_kochwiki_toolset(_ctx: RunContext[None]) -> MCPToolset[None]:
        return create_mcp_toolset(mcp_url, id="kochwiki", identity=current_turn_identity())

    agent = create_turn_agent(
        create_openai_model(
            model_name,
            api_key,
            reasoning_effort=settings.kochwiki_openai_reasoning_effort,
        ),
        instructions=CONVERSATION_INSTRUCTIONS,
        toolsets=[DynamicToolset(create_kochwiki_toolset, per_run_step=False, id="kochwiki")],
        web_search=True,
    )
    agent.name = "kochwiki"
    return agent


def _is_valid_mcp_url(value: str) -> bool:
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
