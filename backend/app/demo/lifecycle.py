from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.agentic.runner import AgentTurnRunner
from app.demo.agent import create_demo_agent


@asynccontextmanager
async def demo_runner() -> AsyncIterator[AgentTurnRunner]:
    async with create_demo_agent() as agent, AgentTurnRunner(agent) as runner:
        yield runner
