from collections.abc import Callable

import pytest

from app.mcp.connection import MCPConnection, MCPConnectionConfig


def stub_connections(
    monkeypatch: pytest.MonkeyPatch, connections: tuple[MCPConnection, ...],
) -> tuple[MCPConnectionConfig, ...]:
    pending = iter(connections)

    def construct(
        name: str, url: str, *, on_connection_lost: Callable[[MCPConnection], None],
    ) -> MCPConnection:
        connection = next(pending)
        assert connection.name == name
        return connection

    monkeypatch.setattr("app.agents.runtime.MCPConnection", construct)
    return tuple(MCPConnectionConfig(connection.name, "http://localhost/mcp/") for connection in connections)
