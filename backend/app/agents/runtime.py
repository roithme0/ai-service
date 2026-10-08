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
        if config.CATALOGUE_REFRESH_SECONDS <= 0:
            raise ValueError("MCP catalogue refresh interval must be positive")
        self.status = RuntimeStatus.CONNECTING
        self._connection_task = asyncio.create_task(self._repair(), name=f"mcp:{self.name}")

    async def _repair(self) -> None:
        try:
            if not await self._initialize_connections():
                return
            if self.status == RuntimeStatus.CLOSING:
                await self._stop.wait()
                return
            valid = self._validate_initial_catalogues()
            await self._poll_catalogues(valid)
        finally:
            if self.status not in (RuntimeStatus.CLOSING, RuntimeStatus.CLOSED):
                self.status = RuntimeStatus.UNAVAILABLE
                if self.issue is None:
                    self.issue = RuntimeIssue("initialization")
            async with AsyncExitStack() as resources:
                for connection in self.mcp_connections:
                    resources.push_async_callback(connection.close)

    async def _initialize_connections(self) -> bool:
        initialized: set[MCPConnection] = set()
        while not self._stop.is_set():
            if self.status == RuntimeStatus.CLOSING:
                await self._stop.wait()
                return False
            self.status = RuntimeStatus.CONNECTING
            for connection in self.mcp_connections:
                if connection in initialized:
                    continue
                try:
                    await connection.start()
                except Exception as error:
                    if self.status == RuntimeStatus.CLOSING:
                        await self._stop.wait()
                        return False
                    retryable = _retryable(error)
                    self.issue = RuntimeIssue(
                        "connection" if retryable else "initialization", connection.name, retryable,
                    )
                    self.status = RuntimeStatus.UNAVAILABLE
                    logger.warning("Agent %s unavailable: MCP initialization failed (%s), retryable=%s",
                                   self.name, type(error).__name__, retryable)
                    if not retryable:
                        await self._stop.wait()
                        return False
                    if await self._wait_or_stop(config.INITIAL_RETRY_SECONDS):
                        return False
                    break
                initialized.add(connection)
            else:
                return True
        return False

    def _validate_initial_catalogues(self) -> set[MCPConnection]:
        try:
            self.mcp_tools.validate()
        except Exception as error:
            for connection in self.mcp_connections:
                connection.tools = ()
            self.issue = RuntimeIssue("catalogue", retryable=True)
            self.status = RuntimeStatus.UNAVAILABLE
            logger.warning("Agent %s unavailable: invalid initial MCP catalogue (%s)",
                           self.name, type(error).__name__)
            return set()
        self.issue = None
        self.status = RuntimeStatus.READY
        return set(self.mcp_connections)

    async def _wait_or_stop(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            if self.status != RuntimeStatus.CLOSING:
                return False
            await self._stop.wait()
        return True

    async def _poll_catalogues(self, valid: set[MCPConnection]) -> None:
        issues: dict[MCPConnection, RuntimeIssue] = {
            connection: RuntimeIssue("catalogue", connection.name, True)
            for connection in self.mcp_connections if connection not in valid
        }
        while not self._stop.is_set():
            if await self._wait_or_stop(config.CATALOGUE_REFRESH_SECONDS):
                return
            for connection in self.mcp_connections:
                try:
                    candidate = await connection.discover_tools()
                    self.mcp_tools.validate({connection: candidate})
                except Exception as error:
                    connection.tools = ()
                    valid.discard(connection)
                    issues[connection] = RuntimeIssue("catalogue", connection.name, True)
                    logger.warning("Agent %s unavailable: MCP catalogue refresh failed (%s/%s)",
                                   self.name, connection.name, type(error).__name__)
                else:
                    connection.tools = candidate
                    valid.add(connection)
                    issues.pop(connection, None)
                if self.status in (RuntimeStatus.CLOSING, RuntimeStatus.CLOSED):
                    await self._stop.wait()
                    return
                self.issue = next(iter(issues.values()), None)
                self.status = RuntimeStatus.READY if len(valid) == len(self.mcp_connections) else RuntimeStatus.UNAVAILABLE

    async def close(self) -> None:
        async with self._close_lock:
            if self.status == RuntimeStatus.CLOSED:
                return
            self.status = RuntimeStatus.CLOSING
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
            if not self._connection_task.done():
                self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                if not self._connection_task.cancelled():
                    raise
        else:
            async with AsyncExitStack() as resources:
                for connection in self.mcp_connections:
                    resources.push_async_callback(connection.close)
