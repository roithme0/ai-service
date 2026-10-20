"""Native MCP configuration for backend-executed tools."""

from httpx2 import AsyncClient
from pydantic_ai.mcp import MCPToolset

from app.agentic.config import (
    MCP_CONNECT_TIMEOUT_SECONDS,
    MCP_READ_TIMEOUT_SECONDS,
    VALIDATION_MAX_RETRIES,
)


def create_mcp_toolset(
    url: str,
    *,
    id: str,
    http_client: AsyncClient | None = None,
) -> MCPToolset[None]:
    return MCPToolset(
        url,
        id=id,
        include_instructions=True,
        tool_error_behavior="failed",
        max_retries=VALIDATION_MAX_RETRIES,
        prefer_tasks=False,
        init_timeout=MCP_CONNECT_TIMEOUT_SECONDS,
        read_timeout=MCP_READ_TIMEOUT_SECONDS,
        http_client=http_client,
    )
