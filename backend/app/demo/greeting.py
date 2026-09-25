"""Greeting tool used by the deterministic demo."""

from __future__ import annotations

import json
from collections.abc import Callable

from app.demo.session import DemoContext, DemoSessionStore, GreetingPayload
from app.sessions.artifacts import ArtifactPrepared, ArtifactPreparationRejected, ArtifactRegistry
from app.sessions.conversation import ConversationStageAccepted, ConversationTurnView, StagedArtifact
from app.sessions.tools import RegisteredTool, ToolExecution, ToolInvocation


type DemoToolFactory = Callable[
    [DemoSessionStore, str, str], RegisteredTool[StagedArtifact[GreetingPayload]]
]


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


class GreetingHandler:
    async def prepare(
        self, view: ConversationTurnView[DemoContext, GreetingPayload], candidate: object
    ) -> ArtifactPrepared[GreetingPayload] | ArtifactPreparationRejected[str]:
        if not isinstance(candidate, str) or not candidate.strip():
            return ArtifactPreparationRejected("invalid_arguments")
        return ArtifactPrepared(GreetingPayload(message=f"Hello, {candidate}!"))


def create_greeting_tool(
    store: DemoSessionStore, session_id: str, turn_id: str
) -> RegisteredTool[StagedArtifact[GreetingPayload]]:
    registry = ArtifactRegistry(((GREETING_ARTIFACT_TYPE, GreetingHandler()),))

    async def execute(call: ToolInvocation) -> ToolExecution[StagedArtifact[GreetingPayload]]:
        try:
            arguments: object = json.loads(call.arguments)
        except (TypeError, ValueError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        if not isinstance(arguments, dict) or set(arguments) != {"name"}:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        name = arguments["name"]
        if not isinstance(name, str) or not name.strip():
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))

        staged = await registry.register(store, session_id, turn_id, GREETING_ARTIFACT_TYPE, name)
        if isinstance(staged, ArtifactPreparationRejected):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": staged.detail}))
        if not isinstance(staged, ConversationStageAccepted):
            return ToolExecution(json.dumps({"kind": staged.kind}))
        return ToolExecution(
            json.dumps({"kind": "created", "artifact_id": staged.artifact.artifact_id}),
            staged.artifact,
        )

    return RegisteredTool("create_greeting", CREATE_GREETING_SCHEMA, execute)
