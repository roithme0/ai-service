"""Agent-owned MCP transport and startup discovery."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
import logging

from mcp import Client
from mcp.types import CallToolResult, DiscoverResult, Tool

from app.mcp.errors import connection_lost

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPConnectionConfig:
    name: str
    url: str


@dataclass(frozen=True)
class MCPDiscovery:
    tools: tuple[Tool, ...]
    instructions: str | None


class MCPConnection:
    def __init__(
        self, name: str, url: str, *,
        on_connection_lost: Callable[[MCPConnection], None] | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._client: Client | None = None
        self._resources: AsyncExitStack | None = None
        self.instructions: str | None = None
        self.tools: tuple[Tool, ...] = ()
        self._broken = False
        self._on_connection_lost = on_connection_lost

    async def start(self) -> None:
        if self._resources is not None:
            raise RuntimeError("MCP connection already started")
        async with AsyncExitStack() as resources:
            client = await resources.enter_async_context(Client(self._url, read_timeout_seconds=60))
            tools = await self._discover_tools(client)
            self.instructions = client.instructions
            self.tools = tools
            self._client = client
            self._broken = False
            self._resources = resources.pop_all()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        if self._resources is None or self._client is None or self._broken:
            raise RuntimeError("MCP connection is not started")
        client = self._client
        try:
            return await client.call_tool(name, arguments)
        except Exception as error:
            self._report_failure(client, error)
            raise

    async def discover(self) -> MCPDiscovery:
        if self._client is None or self._broken:
            raise RuntimeError("MCP connection is not started")
        client = self._client
        try:
            return await self._discover(client)
        except Exception as error:
            self._report_failure(client, error)
            raise

    def _report_failure(self, client: Client, error: BaseException) -> None:
        if client is self._client and not self._broken and connection_lost(error):
            self._broken = True
            if self._on_connection_lost is not None:
                self._on_connection_lost(self)

    async def _discover(self, client: Client) -> MCPDiscovery:
        session = client.session
        version = session.protocol_version
        if session.discover_result is None or version is None:
            raise RuntimeError("MCP instruction refresh requires a modern server")
        result = DiscoverResult.model_validate(await session.send_discover(version))
        if version not in result.supported_versions:
            raise ValueError("MCP server no longer supports the connected protocol version")
        tools = await self._discover_tools(client)
        return MCPDiscovery(tools, result.instructions)

    async def _discover_tools(self, client: Client) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        cursor: str | None = None
        cursors: set[str] = set()
        while True:
            page = await client.list_tools(cursor=cursor, cache_mode="bypass")
            tools.extend(page.tools)
            cursor = page.next_cursor
            if cursor is None:
                return tuple(tools)
            if cursor in cursors:
                raise ValueError("Repeated MCP catalogue cursor")
            cursors.add(cursor)

    async def close(self) -> None:
        resources = self._resources
        self._resources = None
        self._client = None
        self.instructions = None
        self.tools = ()
        if resources is not None:
            try:
                await resources.aclose()
            except Exception as error:
                logger.error("MCP connection cleanup failed (%s/%s)", self.name, type(error).__name__)
                raise
            logger.info("MCP connection closed (%s)", self.name)
