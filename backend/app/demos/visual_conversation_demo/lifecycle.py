from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.capabilities.conversations.runner import AgentTurnRunner
from app.demos.visual_conversation_demo.agent import (
    create_visual_conversation_demo_agent,
)


@asynccontextmanager
async def visual_conversation_demo_runner() -> AsyncIterator[AgentTurnRunner]:
    async with (
        create_visual_conversation_demo_agent() as agent,
        AgentTurnRunner(agent) as runner,
    ):
        yield runner
