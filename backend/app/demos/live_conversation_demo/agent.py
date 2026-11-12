"""Live Demo agent using the shared conversation infrastructure."""

from httpx2 import AsyncClient
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset

from app.capabilities.conversations.mcp import MCPResources, create_mcp_toolset

from app.capabilities.conversations.turns import create_openai_model, create_turn_agent
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo.config import LiveConversationDemoSettings

LIVE_DEMO_INSTRUCTIONS = (
    "You are a helpful conversational assistant in a live demo. "
    "Respond naturally and concisely. "
    "You can present JSON artifacts when useful or requested."
)


def create_live_conversation_demo_agent(
    provider_settings: ProviderSettings,
    settings: LiveConversationDemoSettings,
    *,
    mcp_http_client: AsyncClient,
) -> Agent[None, str]:
    api_key = provider_settings.openai_api_key
    invalid_settings: list[str] = []
    if api_key is None or not api_key.get_secret_value().strip():
        invalid_settings.append("OPENAI_API_KEY")
    model_name = settings.live_demo_openai_model
    if model_name is None:
        invalid_settings.append("LIVE_DEMO_OPENAI_MODEL")
    if invalid_settings:
        raise ValueError(
            f"Invalid or missing agent configuration: {', '.join(invalid_settings)}"
        )
    assert api_key is not None and model_name is not None

    def create_greetings_toolset(_ctx: RunContext[None]) -> MCPToolset[None]:
        return create_mcp_toolset(
            "http://localhost/mcp/", id="greetings", http_client=mcp_http_client
        )

    agent = create_turn_agent(
        create_openai_model(
            model_name,
            api_key,
            reasoning_effort=settings.live_demo_openai_reasoning_effort,
        ),
        instructions=LIVE_DEMO_INSTRUCTIONS,
        capabilities=[MCPResources(create_greetings_toolset, id="greetings")],
    )
    agent.name = "live-demo"
    return agent
