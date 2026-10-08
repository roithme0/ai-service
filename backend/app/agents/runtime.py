"""Availability and external resource ownership for one configured agent."""

import logging
from contextlib import AsyncExitStack
from typing import Generic, Protocol, TypeVar, runtime_checkable

from app.mcp.connection import MCPConnection
from app.mcp.tools import MCPToolset


logger = logging.getLogger(__name__)
AgentT = TypeVar("AgentT")


@runtime_checkable
class AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class AgentRuntime(Generic[AgentT]):
    def __init__(
        self, name: str, agent: AgentT | None, *,
        mcp_connections: tuple[MCPConnection, ...] = (),
        model_client: AsyncCloseable | None = None,
    ) -> None:
        self.name = name
        self.agent = agent
        self.mcp_connections = mcp_connections
        self.mcp_tools = MCPToolset(mcp_connections)
        self._model_client = model_client
        self._started = False
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("Agent runtime is closed")
        if self._started or self.agent is None:
            return
        try:
            for connection in self.mcp_connections:
                await connection.start()
            self.mcp_tools.validate()
        except Exception as error:
            logger.warning("Agent %s unavailable: MCP initialization failed (%s)", self.name, type(error).__name__)
            await self.close()
        except BaseException:
            await self.close()
            raise
        else:
            self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        agent = self.agent
        self.agent = None
        async with AsyncExitStack() as resources:
            if self._model_client is not None:
                resources.push_async_callback(self._model_client.close)
            for connection in self.mcp_connections:
                resources.push_async_callback(connection.close)
            if isinstance(agent, AsyncCloseable):
                resources.push_async_callback(agent.close)
