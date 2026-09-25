"""Greeting tool used by the deterministic demo."""

from __future__ import annotations

import json

from app.demo.session import DemoArtifact, DemoSessionStore, GreetingPayload
from app.sessions.conversation import ConversationStageAccepted, StagedArtifact
from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation


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


def create_greeting_tool(
    store: DemoSessionStore, session_id: str, turn_id: str
) -> RegisteredTool[StagedArtifact[DemoArtifact]]:
    def execute(call: ToolInvocation) -> ToolExecution[StagedArtifact[DemoArtifact]]:
        try:
            arguments: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        if not isinstance(arguments, dict) or set(arguments) != {"name"}:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip():
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))

        artifact = DemoArtifact(payload=GreetingPayload(message=f"Hello, {name}!"))
        staged = store.stage_artifact(session_id, turn_id, artifact)
        if not isinstance(staged, ConversationStageAccepted):
            return ToolExecution(json.dumps({"kind": staged.kind}))
        return ToolExecution(
            json.dumps({"kind": "created", "artifact_id": staged.artifact.artifact_id}),
            staged.artifact,
        )

    return RegisteredTool("create_greeting", CREATE_GREETING_SCHEMA, execute)
