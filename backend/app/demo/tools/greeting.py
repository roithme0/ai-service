"""Greeting tool used by the deterministic demo."""

from __future__ import annotations

import json

from app.demo.session import DemoPayload, GreetingPayload
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.sessions.models.execution import ToolExecution


CREATE_GREETING_SCHEMA: dict[str, object] = {
    "type": "function",
    "name": "create_greeting",
    "description": "Create a greeting artifact for a named person.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    },
}


GREETING_ARTIFACT_TYPE = "demo.greeting"


def create_greeting_tool() -> RegisteredTool[ArtifactCandidate[DemoPayload]]:
    async def execute(call: ToolInvocation) -> ToolExecution[ArtifactCandidate[DemoPayload]]:
        try:
            arguments: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        if not isinstance(arguments, dict) or set(arguments) != {"name"}:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip():
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        payload = GreetingPayload(message=f"Hello, {name}!")
        return ToolExecution(ArtifactToolOutput("created"), ArtifactCandidate(GREETING_ARTIFACT_TYPE, payload))

    return RegisteredTool("create_greeting", CREATE_GREETING_SCHEMA, execute)
