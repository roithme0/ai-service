"""Live Demo agent using the shared conversation infrastructure."""

from pydantic_ai import Agent

from app.capabilities.conversations.turns import create_openai_model, create_turn_agent
from app.core.config import ProviderSettings

LIVE_DEMO_INSTRUCTIONS = (
    "You are a helpful conversational assistant in a live demo. "
    "Respond naturally and concisely. "
    "You can present JSON artifacts when useful or requested."
)


def create_live_conversation_demo_agent(
    provider_settings: ProviderSettings,
) -> Agent[None, str]:
    api_key = provider_settings.openai_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise ValueError("Invalid or missing agent configuration: OPENAI_API_KEY")
    agent = create_turn_agent(
        create_openai_model("gpt-6-luna", api_key, reasoning_effort="medium"),
        instructions=LIVE_DEMO_INSTRUCTIONS,
    )
    agent.name = "live-demo"
    return agent
