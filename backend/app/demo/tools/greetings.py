"""Greeting-list tool used by the deterministic demo."""

from __future__ import annotations

import json

from app.demo.session import DemoContext, DemoPayload, DemoSessionStore, GreetingsPayload
from app.sessions.artifacts import ArtifactPrepared, ArtifactPreparationRejected, ArtifactRegistry
from app.sessions.conversation import ConversationStageAccepted, ConversationTurnView, StagedArtifact
from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation


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


class GreetingsHandler:
    async def prepare(
        self, view: ConversationTurnView[DemoContext, DemoPayload], candidate: object
    ) -> ArtifactPrepared[DemoPayload] | ArtifactPreparationRejected[str]:
        if not isinstance(candidate, list) or not candidate:
            return ArtifactPreparationRejected("invalid_arguments")
        messages: list[str] = []
        for name in candidate:
            if not isinstance(name, str) or not name.strip():
                return ArtifactPreparationRejected("invalid_arguments")
            messages.append(f"Hello, {name}!")
        return ArtifactPrepared(GreetingsPayload(messages=tuple(messages)))


def create_greetings_tool(
    store: DemoSessionStore, session_id: str, turn_id: str
) -> RegisteredTool[StagedArtifact[DemoPayload]]:
    registry = ArtifactRegistry[DemoContext, DemoPayload, str](((GREETINGS_ARTIFACT_TYPE, GreetingsHandler()),))

    async def execute(call: ToolInvocation) -> ToolExecution[StagedArtifact[DemoPayload]]:
        try:
            arguments: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        if not isinstance(arguments, dict) or set(arguments) != {"names"}:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        staged = await registry.register(store, session_id, turn_id, GREETINGS_ARTIFACT_TYPE, arguments["names"])
        if isinstance(staged, ArtifactPreparationRejected):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": staged.detail}))
        if not isinstance(staged, ConversationStageAccepted):
            return ToolExecution(json.dumps({"kind": staged.kind}))
        return ToolExecution(
            json.dumps({"kind": "created", "artifact_id": staged.artifact.artifact_id}),
            staged.artifact,
        )

    return RegisteredTool("create_greetings", CREATE_GREETINGS_SCHEMA, execute)
