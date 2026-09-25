import asyncio
import json

import pytest

from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation, ToolRegistry


def test_direct_invocation_returns_typed_result_and_forwards_arguments() -> None:
    received: list[ToolInvocation] = []

    async def execute(call: ToolInvocation) -> ToolExecution[str]:
        received.append(call)
        return ToolExecution(json.dumps({"message": "Hello, World!"}), "greeting artifact")

    registry = ToolRegistry((RegisteredTool(
        "create_greeting", {"type": "function", "name": "create_greeting"}, execute,
    ),))
    result = asyncio.run(registry.invoke("create_greeting", '{"name":"World"}'))

    assert received == [ToolInvocation("create_greeting", '{"name":"World"}')]
    assert json.loads(result.output) == {"message": "Hello, World!"}
    assert result.artifact == "greeting artifact"


def test_unknown_tool_is_rejected_and_invalid_arguments_reach_selected_tool() -> None:
    received: list[str] = []

    def execute(call: ToolInvocation) -> ToolExecution[str]:
        received.append(call.arguments)
        try:
            json.loads(call.arguments)
        except json.JSONDecodeError:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        return ToolExecution("accepted")

    registry = ToolRegistry((RegisteredTool("sample", {"type": "function", "name": "sample"}, execute),))
    unknown = asyncio.run(registry.invoke("other", "{}"))
    invalid = asyncio.run(registry.invoke("sample", "{"))

    assert json.loads(unknown.output) == {"kind": "rejected", "reason": "unknown_tool"}
    assert json.loads(invalid.output) == {"kind": "rejected", "reason": "invalid_arguments"}
    assert received == ["{"]


def test_registration_rejects_duplicate_names_and_schema_mismatch() -> None:
    def execute(call: ToolInvocation) -> ToolExecution[str]:
        return ToolExecution("unused")

    registered = RegisteredTool("sample", {"type": "function", "name": "sample"}, execute)
    with pytest.raises(ValueError, match="unique names"):
        ToolRegistry((registered, registered))
    with pytest.raises(ValueError, match="matching their schemas"):
        ToolRegistry((RegisteredTool("sample", {"type": "function", "name": "other"}, execute),))
