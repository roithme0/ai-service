"""Native MCP configuration for backend-executed tools."""

from httpx2 import AsyncClient
from pydantic_ai.mcp import MCPToolset

from app.capabilities.conversations.config import (
    MCP_CONNECT_TIMEOUT_SECONDS,
    MCP_READ_TIMEOUT_SECONDS,
    VALIDATION_MAX_RETRIES,
)
from app.core.identity import ApplicationIdentity


def create_mcp_toolset(
    url: str,
    *,
    id: str,
    identity: ApplicationIdentity | None = None,
    http_client: AsyncClient | None = None,
) -> MCPToolset[None]:
    return MCPToolset(
        url,
        id=id,
        headers={"X-Application-User": identity.to_header()} if identity is not None else None,
        include_instructions=True,
        tool_error_behavior="failed",
        max_retries=VALIDATION_MAX_RETRIES,
        prefer_tasks=False,
        init_timeout=MCP_CONNECT_TIMEOUT_SECONDS,
        read_timeout=MCP_READ_TIMEOUT_SECONDS,
        http_client=http_client,
    )
