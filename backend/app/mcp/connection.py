"""Agent-owned MCP transport and startup discovery."""

from contextlib import AsyncExitStack
from dataclasses import dataclass

from mcp import Client
from mcp.types import CallToolResult, DiscoverResult, Tool


@dataclass(frozen=True)
class MCPDiscovery:
    tools: tuple[Tool, ...]
    instructions: str | None


class MCPConnection:
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self._url = url
        self._client: Client | None = None
        self._resources: AsyncExitStack | None = None
        self.instructions: str | None = None
        self.tools: tuple[Tool, ...] = ()

    async def start(self) -> None:
        if self._resources is not None:
            raise RuntimeError("MCP connection already started")
        async with AsyncExitStack() as resources:
            client = await resources.enter_async_context(Client(self._url, read_timeout_seconds=60))
            tools = await self._discover_tools(client)
            self.instructions = client.instructions
            self.tools = tools
            self._client = client
            self._resources = resources.pop_all()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        if self._resources is None or self._client is None:
            raise RuntimeError("MCP connection is not started")
        return await self._client.call_tool(name, arguments)

    async def discover(self) -> MCPDiscovery:
        if self._client is None:
            raise RuntimeError("MCP connection is not started")
        session = self._client.session
        version = session.protocol_version
        if session.discover_result is None or version is None:
            raise RuntimeError("MCP instruction refresh requires a modern server")
        result = DiscoverResult.model_validate(await session.send_discover(version))
        if version not in result.supported_versions:
            raise ValueError("MCP server no longer supports the connected protocol version")
        tools = await self._discover_tools(self._client)
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
            await resources.aclose()
