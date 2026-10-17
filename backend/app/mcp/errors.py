"""Classify failures that require replacing an established MCP transport."""

import anyio
import httpx2
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, INTERNAL_ERROR, INVALID_REQUEST


def connection_lost(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return all(connection_lost(child) for child in error.exceptions)
    if isinstance(error, MCPError):
        return (error.code == CONNECTION_CLOSED
                or (error.code == INVALID_REQUEST and error.message == "Session terminated")
                or (error.code == INTERNAL_ERROR and error.message == "Server returned an error response"))
    if isinstance(error, (TimeoutError, httpx2.TimeoutException)):
        return False
    return isinstance(error, (httpx2.TransportError, ConnectionError,
                              anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError))
