import asyncio

import httpx
import pytest
from pydantic_ai import models

from app.capabilities.conversations.http import SnapshotEvent
from app.capabilities.conversations.presentation import (
    AcceptedArtifact,
    AssistantText,
    PresentedSession,
    PresentedTurn,
    ToolActivity,
)
from app.capabilities.conversations.runner import AgentTurnRunner
from app.demos.visual_conversation_demo.agent import (
    COMPLETE_REPLY,
    FAILED_GENERATION_UPDATE,
    FIRST_REPLY,
    SECOND_REPLY,
    create_visual_conversation_demo_agent,
)
from app import main
from app.main import app
from tests.capabilities.conversations.test_http import stream

BASE = "/api/v1/agents/demo/sessions"
CAPABILITIES = [
    {
        "type": "json",
        "description": "Display structured JSON data for inspection.",
        "payloadSchema": {
            "type": "object",
            "properties": {"value": {}},
            "required": ["value"],
            "additionalProperties": False,
        },
    }
]


def _turns(snapshot: PresentedSession) -> list[PresentedTurn]:
    return [item for item in snapshot.history if isinstance(item, PresentedTurn)]


def test_visual_conversation_demo_through_http_and_live_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    async def exercise() -> None:
        agent = create_visual_conversation_demo_agent(delay_seconds=0)
        async with agent, AgentTurnRunner(agent) as runner:
            monkeypatch.setitem(
                app.dependency_overrides,
                main.get_agent_registry,
                lambda: {"demo": runner},
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://test",
                headers={"X-Application-User": "test:alice"},
            ) as client:
                created = await client.post(
                    BASE,
                    json={
                        "initial_context": {"hidden": "SECRET_CONTEXT"},
                        "artifact_capabilities": CAPABILITIES,
                    },
                )
                assert created.status_code == 201
                path = f"{BASE}/{created.json()['session_id']}"
                assert (
                    await client.get(path, headers={"X-Application-User": "test:bob"})
                ).status_code == 404
                async with stream(app, f"{path}/events") as updates:
                    initial = await updates.event()
                    assert (
                        isinstance(initial, SnapshotEvent)
                        and initial.snapshot.history == ()
                    )
                    snapshots: list[PresentedSession] = []
                    for ordinal, status in enumerate(
                        ("completed", "completed", "failed", "completed"), 1
                    ):
                        response = await client.post(
                            f"{path}/turns", json={"prompt": "Same text every time"}
                        )
                        assert response.status_code == 202 and response.json() == {
                            "kind": "accepted"
                        }
                        snapshots.append(
                            await updates.until(
                                lambda snapshot: len(_turns(snapshot)) == ordinal
                                and _turns(snapshot)[-1].lifecycle.status == status
                            )
                        )
                    final_turns = _turns(snapshots[-1])
                    assert "SECRET_CONTEXT" not in snapshots[-1].model_dump_json()
                    assert [
                        part.content
                        for turn in final_turns
                        for part in turn.parts
                        if isinstance(part, AssistantText)
                        and part.phase == "final_answer"
                    ] == [FIRST_REPLY, SECOND_REPLY, COMPLETE_REPLY]
                    second = final_turns[1]
                    assert [part.part_kind for part in second.parts] == [
                        "text",
                        "tool-call",
                        "artifact",
                        "text",
                        "tool-call",
                        "artifact",
                        "text",
                        "tool-call",
                        "text",
                    ]
                    assert [
                        part.status
                        for part in second.parts
                        if isinstance(part, ToolActivity)
                    ] == ["success", "success", "failed"]
                    artifacts = [
                        part.artifact
                        for part in second.parts
                        if isinstance(part, AcceptedArtifact)
                    ]
                    assert [artifact.type for artifact in artifacts] == ["json", "json"]
                    assert [artifact.content.title for artifact in artifacts] == [
                        "demo.greeting",
                        "demo.greetings",
                    ]
                    assert artifacts[0].content.payload == {
                        "value": {"message": "Hello, World!"}
                    }
                    assert artifacts[1].content.payload == {
                        "value": {
                            "messages": [f"Hello, Visitor {i}!" for i in range(1, 31)]
                        }
                    }
                    assert final_turns[2].parts == (
                        AssistantText(
                            content=FAILED_GENERATION_UPDATE, phase="commentary"
                        ),
                    )
                    assert (await client.get(path)).json() == snapshots[-1].model_dump(
                        mode="json"
                    )
                fresh = await client.post(
                    BASE, json={"artifact_capabilities": CAPABILITIES}
                )
                fresh_path = f"{BASE}/{fresh.json()['session_id']}"
                await client.post(f"{fresh_path}/turns", json={"prompt": "Fresh"})
                async with stream(app, f"{fresh_path}/events") as updates:
                    reset = await updates.until(
                        lambda snapshot: bool(_turns(snapshot))
                        and _turns(snapshot)[-1].lifecycle.status == "completed"
                    )
                    assert _turns(reset)[0].parts == (
                        AssistantText(content=FIRST_REPLY, phase="final_answer"),
                    )

    asyncio.run(exercise())
