"""Exercise native tool execution and follow-up history with the configured model."""

import asyncio
from uuid import uuid4

from pydantic_ai import Tool
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from app.capabilities.conversations.turns import create_openai_model, create_turn_agent, execute_turn
from app.core.config import ProviderSettings
from app.capabilities.conversations.config import KochwikiConversationSettings


async def verify() -> None:
    settings = KochwikiConversationSettings()
    provider_settings = ProviderSettings()
    if provider_settings.openai_api_key is None or settings.kochwiki_openai_model is None:
        raise SystemExit("Set OPENAI_API_KEY and KOCHWIKI_OPENAI_MODEL in backend/.env.")

    probe_value = uuid4().hex
    calls = 0

    def lookup_probe_value() -> str:
        """Retrieve the verification value for this conversation."""
        nonlocal calls
        calls += 1
        return probe_value

    agent = create_turn_agent(
        create_openai_model(
            settings.kochwiki_openai_model,
            provider_settings.openai_api_key,
            reasoning_effort=settings.kochwiki_openai_reasoning_effort,
        ),
        instructions="Use the lookup tool when asked for the verification value. Reply with its exact value.",
        tools=[Tool(lookup_probe_value)],
    )
    async with agent:
        first = await execute_turn(agent, "Look up the verification value and tell me what it is.")
        assert calls == 1 and probe_value in first.output, "First turn did not use the tool result."
        second = await execute_turn(
            agent,
            "Repeat the verification value from our conversation without calling a tool.",
            conversation=first.conversation,
        )
        assert calls == 1 and probe_value in second.output, "Follow-up did not reuse history."

    for number, result in enumerate((first, second), start=1):
        print(f"Turn {number}: {result.output}")
        for message in result.new_messages():
            for part in message.parts:
                if isinstance(part, (ToolCallPart, ToolReturnPart)):
                    print(f"  {part.part_kind}: {part.tool_name} ({part.tool_call_id})")
        print(f"  Cumulative usage: {result.usage}")
    print("Verified native tool execution and follow-up history without replaying the tool.")


if __name__ == "__main__":
    asyncio.run(verify())
