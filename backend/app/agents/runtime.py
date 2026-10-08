"""Availability and external resource ownership for one configured agent."""

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

import anyio
import httpx2
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

from app.agents.enums.runtime import RuntimeStatus
from app.mcp import config
from app.mcp.connection import MCPConnection
from app.mcp.tools import MCPToolset


logger = logging.getLogger(__name__)
AgentT = TypeVar("AgentT")


@dataclass(frozen=True)
class RuntimeIssue:
    kind: Literal["configuration", "connection", "catalogue", "initialization"]
    connection: str | None = None
    retryable: bool = False


def _retryable(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return all(_retryable(child) for child in error.exceptions)
    if isinstance(error, MCPError):
        return error.code in (CONNECTION_CLOSED, REQUEST_TIMEOUT)
    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.status_code >= 500 or error.response.status_code in (408, 429)
    return isinstance(error, (httpx2.TransportError, ConnectionError, TimeoutError,
                              anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError))


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
        self.status = RuntimeStatus.CREATED
        self.issue: RuntimeIssue | None = None
        self._connection_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._close_lock = asyncio.Lock()

    async def start(self) -> None:
        if self.status in (RuntimeStatus.CLOSING, RuntimeStatus.CLOSED):
            raise RuntimeError("Agent runtime is closed")
        if self.status != RuntimeStatus.CREATED:
            return
        if self.agent is None:
            self.status = RuntimeStatus.UNAVAILABLE
            self.issue = RuntimeIssue("configuration")
            return
        if not self.mcp_connections:
            self.status = RuntimeStatus.READY
            return
        if config.INITIAL_RETRY_SECONDS <= 0:
            raise ValueError("MCP retry interval must be positive")
        self.status = RuntimeStatus.CONNECTING
        self._connection_task = asyncio.create_task(self._repair(), name=f"mcp:{self.name}")

    async def _repair(self) -> None:
        initialized: set[MCPConnection] = set()
        try:
            while not self._stop.is_set():
                self.status = RuntimeStatus.CONNECTING
                failed_connection: str | None = None
                try:
                    for connection in self.mcp_connections:
                        if connection not in initialized:
                            failed_connection = connection.name
                            await connection.start()
                            initialized.add(connection)
                    failed_connection = None
                    self.mcp_tools.validate()
                except Exception as error:
                    retryable = _retryable(error)
                    self.issue = RuntimeIssue(
                        "connection" if retryable else ("catalogue" if failed_connection is None else "initialization"),
                        failed_connection, retryable,
                    )
                    self.status = RuntimeStatus.UNAVAILABLE
                    logger.warning("Agent %s unavailable: MCP initialization failed (%s), retryable=%s",
                                   self.name, type(error).__name__, retryable)
                    if not retryable:
                        await self._stop.wait()
                        return
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=config.INITIAL_RETRY_SECONDS)
                    except TimeoutError:
                        continue
                    return
                self.issue = None
                self.status = RuntimeStatus.READY
                await self._stop.wait()
                return
        finally:
            if self.status not in (RuntimeStatus.CLOSING, RuntimeStatus.CLOSED):
                self.status = RuntimeStatus.UNAVAILABLE
                if self.issue is None:
                    self.issue = RuntimeIssue("initialization")
            async with AsyncExitStack() as resources:
                for connection in self.mcp_connections:
                    resources.push_async_callback(connection.close)

    async def close(self) -> None:
        async with self._close_lock:
            if self.status == RuntimeStatus.CLOSED:
                return
            previous = self.status
            self.status = RuntimeStatus.CLOSING
            if self._connection_task is not None and previous != RuntimeStatus.READY and not self._connection_task.done():
                self._connection_task.cancel()
            agent = self.agent
            self.agent = None
            try:
                async with AsyncExitStack() as resources:
                    if self._model_client is not None:
                        resources.push_async_callback(self._model_client.close)
                    resources.push_async_callback(self._close_connections)
                    if isinstance(agent, AsyncCloseable):
                        resources.push_async_callback(agent.close)
            finally:
                self.status = RuntimeStatus.CLOSED

    async def _close_connections(self) -> None:
        self._stop.set()
        if self._connection_task is not None:
            try:
                await self._connection_task
            except asyncio.CancelledError:
                if not self._connection_task.cancelled():
                    raise
        else:
            async with AsyncExitStack() as resources:
                for connection in self.mcp_connections:
                    resources.push_async_callback(connection.close)
