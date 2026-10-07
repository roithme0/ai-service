"""Shared lifecycle for the configured agent runtimes."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass

from app.agents.runtime import AgentRuntime
from app.demo.agent import DemoAgent
from app.sessions.model_sessions import ModelAgent


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
