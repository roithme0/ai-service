"""Expose agent-owned MCP capabilities to the provider-neutral tool loop."""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Never

from app.mcp.connection import MCPConnection
from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation


logger = logging.getLogger(__name__)


def model_tool_name(connection: str, tool: str) -> str:
    name = f"{connection}__{tool}"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError(f"Unsupported model-facing MCP tool name: {name}")
    return name


class MCPToolset:
    def __init__(self, connections: tuple[MCPConnection, ...]) -> None:
        names = [connection.name for connection in connections]
        if len(names) != len(set(names)) or any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names
        ):
            raise ValueError("MCP connection names must be unique, nonempty identifiers within an agent")
        self._connections = connections

    def validate(self) -> None:
        names: set[str] = set()
        for connection in self._connections:
            for tool in connection.tools:
                name = model_tool_name(connection.name, tool.name)
                if name in names:
                    raise ValueError(f"Duplicate model-facing MCP tool name: {name}")
                names.add(name)

    def registered_tools(self) -> tuple[RegisteredTool[Never], ...]:
        self.validate()
        tools: list[RegisteredTool[Never]] = []
        for connection in self._connections:
            for tool in connection.tools:
                name = model_tool_name(connection.name, tool.name)
                tools.append(RegisteredTool(
                    name,
                    {"type": "function", "name": name, "description": tool.description or "",
                     "parameters": tool.input_schema, "strict": False},
                    _executor(connection, tool.name),
                ))
        return tuple(tools)

    @property
    def instructions(self) -> str:
        sections: list[str] = []
        for connection in self._connections:
            mapping = "\n".join(
                f"{tool.name} -> {model_tool_name(connection.name, tool.name)}"
                for tool in connection.tools
            )
            sections.append(
                f"MCP server {connection.name}\n"
                f"Use the following model-facing names when this server refers to its tools:\n{mapping}\n"
                f"Server instructions:\n{connection.instructions or ''}"
            )
        return "\n\n".join(sections)


def _executor(
    connection: MCPConnection, tool_name: str,
) -> Callable[[ToolInvocation], Awaitable[ToolExecution[Never]]]:
    async def execute(invocation: ToolInvocation) -> ToolExecution[Never]:
        try:
            arguments: object = json.loads(invocation.arguments, parse_constant=_reject_constant)
        except ValueError:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        if not isinstance(arguments, dict):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        try:
            result = await connection.call_tool(tool_name, arguments)
        except Exception as error:
            logger.warning("MCP tool call failed (%s/%s, %s)", connection.name, tool_name, type(error).__name__)
            return ToolExecution(json.dumps({"kind": "tool_failed", "reason": "mcp_call_failed"}), failed=True)
        return ToolExecution(result.model_dump_json(by_alias=True, exclude_none=True), failed=result.is_error)

    return execute


def _reject_constant(value: str) -> object:
    raise ValueError(f"Invalid JSON constant: {value}")
