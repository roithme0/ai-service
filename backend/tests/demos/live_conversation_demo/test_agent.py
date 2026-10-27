import asyncio
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_ai import Agent, models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.usage import RequestUsage

from app import lifespan
from app.main import app
from app.capabilities.conversations.presentation import (
    AcceptedArtifact,
    AssistantText,
    PresentedTurn,
    ToolActivity,
)
from app.capabilities.conversations.runner import AgentTurnRunner
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo import lifecycle
from app.demos.live_conversation_demo.agent import create_live_conversation_demo_agent
from tests.capabilities.conversations.test_http import stream

BASE = "/api/v1/agents/live-demo/sessions"


@pytest.mark.parametrize("key", [None, "", "   ", SecretStr("   ")])
def test_live_demo_requires_shared_provider_credentials(
    key: str | SecretStr | None,
) -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_live_conversation_demo_agent(
            ProviderSettings(_env_file=None, openai_api_key=key)
        )


@pytest.mark.parametrize(
    "failure", [ValueError("Missing key"), RuntimeError("Private startup detail")]
)
def test_live_demo_startup_failure_keeps_visual_demo_available(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    def unavailable(settings: ProviderSettings) -> Agent[None, str]:
        raise failure

    monkeypatch.setattr(lifecycle, "create_live_conversation_demo_agent", unavailable)
    with TestClient(app) as client:
        headers = {"X-Application-User": "demo:default"}
        response = client.post(BASE, json={}, headers=headers)
        assert response.status_code == 503
        assert response.json() == {"kind": "agent_unavailable"}
        assert (
            client.post(
                "/api/v1/agents/visual-demo/sessions", json={}, headers=headers
            ).status_code
            == 201
        )


def test_live_demo_configuration_and_session_artifacts_through_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    agent = create_live_conversation_demo_agent(
        ProviderSettings(_env_file=None, openai_api_key="test-key")
    )
    assert agent.name == "live-demo"
    model = agent.model
    assert isinstance(model, OpenAIResponsesModel)
    assert model.model_name == "gpt-6-luna"
    assert model.settings is not None
    assert model.settings["openai_reasoning_effort"] == "medium"
    assert model.settings["openai_store"] is False
    assert model.client.api_key == "test-key"
    monkeypatch.setattr(
        lifecycle, "create_live_conversation_demo_agent", lambda settings: agent
    )
    monkeypatch.setattr(
        lifespan, "get_provider_settings", lambda: ProviderSettings(_env_file=None)
    )

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert not info.model_request_parameters.native_tools
        assert {tool.name for tool in info.function_tools} == {"present_artifact"}
        usage = RequestUsage(input_tokens=10, output_tokens=5, cost=Decimal("0.001"))
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(
                parts=[TextPart("Your artifact is ready.")], usage=usage
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "present_artifact",
                    {
                        "type": "json",
                        "content": {
                            "title": "Example",
                            "payload": {"value": {"hello": "world"}},
                        },
                    },
                )
            ],
            usage=usage,
        )

    async def exercise() -> None:
        async with app.router.lifespan_context(app):
            with agent.override(model=FunctionModel(respond)):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app),
                    base_url="http://test",
                    headers={"X-Application-User": "test:alice"},
                ) as client:
                    created = await client.post(
                        BASE,
                        json={
                            "artifact_capabilities": [
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
                        },
                    )
                    assert created.status_code == 201
                    path = f"{BASE}/{created.json()['session_id']}"
                    async with stream(app, f"{path}/events") as updates:
                        response = await client.post(
                            f"{path}/turns",
                            json={"prompt": "Present a hello world JSON artifact."},
                        )
                        assert response.status_code == 202
                        snapshot = await updates.until(
                            lambda snapshot: any(
                                isinstance(item, PresentedTurn)
                                and item.lifecycle.status in ("completed", "failed")
                                for item in snapshot.history
                            )
                        )
                    turn = next(
                        item
                        for item in snapshot.history
                        if isinstance(item, PresentedTurn)
                    )
                    assert turn.lifecycle.status == "completed"
                    assert any(
                        isinstance(part, AssistantText)
                        and part.content == "Your artifact is ready."
                        for part in turn.parts
                    )
                    activity = next(
                        part for part in turn.parts if isinstance(part, ToolActivity)
                    )
                    assert (
                        activity.tool_name == "present_artifact"
                        and activity.status == "success"
                    )
                    artifact = next(
                        part
                        for part in turn.parts
                        if isinstance(part, AcceptedArtifact)
                    )
                    assert artifact.artifact.content.payload == {
                        "value": {"hello": "world"}
                    }
                    assert turn.usage.requests == 2 and turn.usage.tool_calls == 1
                    assert (
                        turn.usage.input_tokens == 20 and turn.usage.output_tokens == 10
                    )
                    assert turn.usage.estimated_cost_usd == Decimal("0.002")
                    assert snapshot.usage == turn.usage
                    assert (await client.get(path)).json() == snapshot.model_dump(
                        mode="json"
                    )
        assert model.client.is_closed()

    asyncio.run(exercise())


def test_partial_live_runner_startup_closes_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = create_live_conversation_demo_agent(
        ProviderSettings(_env_file=None, openai_api_key="test-key")
    )
    model = agent.model
    assert isinstance(model, OpenAIResponsesModel)
    monkeypatch.setattr(
        lifecycle, "create_live_conversation_demo_agent", lambda settings: agent
    )

    async def fail_start(runner: AgentTurnRunner) -> AgentTurnRunner:
        raise RuntimeError("Runner initialization failed")

    monkeypatch.setattr(AgentTurnRunner, "__aenter__", fail_start)

    async def exercise() -> None:
        async with lifecycle.live_conversation_demo_runner(
            ProviderSettings(_env_file=None)
        ) as runner:
            assert runner is None
            assert model.client.is_closed()

    asyncio.run(exercise())
