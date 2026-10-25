import asyncio
from contextlib import nullcontext

import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel

from app import lifespan
from app.capabilities.conversations import lifecycle
from app.capabilities.conversations.config import KochwikiConversationSettings
from app.capabilities.conversations.runner import AgentTurnRunner, RunnerClosedError
from app.capabilities.conversations.turns import create_openai_model
from app.capabilities.embeddings.service import EmbeddingService
from app.core.config import ProviderSettings
from app.core.identity import ApplicationIdentity
from app.demos.visual_conversation_demo import lifecycle as visual_conversation_demo_lifecycle


@pytest.fixture
def configured_model(monkeypatch: pytest.MonkeyPatch) -> OpenAIResponsesModel:
    model = create_openai_model("gpt-5.2", SecretStr("test-key"), reasoning_effort=None)
    agent: Agent[None, str] = Agent(model)

    def create(
        settings: KochwikiConversationSettings, *, provider_settings: ProviderSettings,
    ) -> Agent[None, str]:
        return agent

    monkeypatch.setattr(lifecycle, "create_kochwiki_agent", create)
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    return model


def test_later_application_startup_failure_closes_started_capabilities(
    configured_model: OpenAIResponsesModel, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EmbeddingService(AsyncOpenAI(api_key="test-key"))
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: service)
    monkeypatch.setattr(lifespan, "get_provider_settings", lambda: ProviderSettings(_env_file=None))

    def fail_demo() -> Agent[None, str]:
        raise RuntimeError("Demo initialization failed")

    monkeypatch.setattr(visual_conversation_demo_lifecycle, "create_visual_conversation_demo_agent", fail_demo)

    async def exercise() -> None:
        application = FastAPI()
        with pytest.raises(RuntimeError, match="Demo initialization failed"):
            async with lifespan.application_lifespan(application):
                raise AssertionError("Startup should have failed")
        assert service.client is not None and service.client.is_closed()
        assert configured_model.client.is_closed()
        assert application.state.agent_runners == {"kochwiki": None, "demo": None}

    asyncio.run(exercise())


@pytest.mark.parametrize("fail_body", [False, True])
def test_application_shutdown_clears_registry_and_closes_all_resources(
    configured_model: OpenAIResponsesModel, monkeypatch: pytest.MonkeyPatch, fail_body: bool,
) -> None:
    service = EmbeddingService(AsyncOpenAI(api_key="test-key"))
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: service)
    monkeypatch.setattr(lifespan, "get_provider_settings", lambda: ProviderSettings(_env_file=None))

    async def exercise() -> None:
        application = FastAPI()
        with pytest.raises(LookupError, match="Application failure") if fail_body else nullcontext():
            async with lifespan.application_lifespan(application):
                runners: dict[str, AgentTurnRunner | None] = application.state.agent_runners
                active_runners = tuple(runners.values())
                assert all(runner is not None for runner in active_runners)
                assert application.state.embedding_service is service
                assert service.client is not None and not service.client.is_closed()
                assert not configured_model.client.is_closed()
                if fail_body:
                    raise LookupError("Application failure")
        assert runners == {"kochwiki": None, "demo": None}
        assert service.client is not None and service.client.is_closed()
        assert configured_model.client.is_closed()
        for runner in active_runners:
            assert runner is not None
            with pytest.raises(RunnerClosedError):
                runner.create_session(owner=ApplicationIdentity("test", "user"))

    asyncio.run(exercise())
