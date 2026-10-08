"""Greeting-list tool used by the deterministic demo."""

from __future__ import annotations

import json

from app.demo.session import DemoPayload, GreetingsPayload
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactToolOutput
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.sessions.models.execution import ToolExecution


GREETINGS_ARTIFACT_TYPE = "demo.greetings"
CREATE_GREETINGS_SCHEMA: dict[str, object] = {
    "type": "function",
    "name": "create_greetings",
    "description": "Create an artifact containing a list of greetings for named people.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["names"],
        "properties": {"names": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
    },
}


def create_greetings_tool() -> RegisteredTool[ArtifactCandidate[DemoPayload]]:
    async def execute(call: ToolInvocation) -> ToolExecution[ArtifactCandidate[DemoPayload]]:
        try:
            arguments: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        if not isinstance(arguments, dict) or set(arguments) != {"names"}:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        names = arguments["names"]
        if not isinstance(names, list) or not names or any(not isinstance(name, str) or not name.strip() for name in names):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        payload = GreetingsPayload(messages=tuple(f"Hello, {name}!" for name in names))
        return ToolExecution(ArtifactToolOutput("created"), ArtifactCandidate(GREETINGS_ARTIFACT_TYPE, payload))

    return RegisteredTool("create_greetings", CREATE_GREETINGS_SCHEMA, execute)
