"""Agent-owned MCP transport and startup discovery."""

from contextlib import AsyncExitStack

from mcp import Client
from mcp.types import CallToolResult, Tool


class MCPConnection:
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self._client = Client(url, read_timeout_seconds=60)
        self._resources: AsyncExitStack | None = None
        self.instructions: str | None = None
        self.tools: tuple[Tool, ...] = ()

    async def start(self) -> None:
        if self._resources is not None:
            raise RuntimeError("MCP connection already started")
        async with AsyncExitStack() as resources:
            client = await resources.enter_async_context(self._client)
            tools: list[Tool] = []
            cursor: str | None = None
            while True:
                page = await client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if cursor is None:
                    break
            self.instructions = client.instructions
            self.tools = tuple(tools)
            self._resources = resources.pop_all()

    async def call_tool(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        if self._resources is None:
            raise RuntimeError("MCP connection is not started")
        return await self._client.call_tool(name, arguments)

    async def close(self) -> None:
        resources = self._resources
        self._resources = None
        self.instructions = None
        self.tools = ()
        if resources is not None:
            await resources.aclose()
