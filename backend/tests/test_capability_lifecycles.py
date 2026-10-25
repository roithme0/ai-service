import asyncio

from fastapi import FastAPI
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
import pytest

from app import main
from app.agentic import lifecycle
from app.agentic.config import KochwikiConversationSettings
from app.agentic.runner import AgentTurnRunner, RunnerClosedError
from app.agentic.turns import create_openai_model
from app.core.config import ProviderSettings
from app.core.identity import ApplicationIdentity
from app.demo import lifecycle as demo_lifecycle
from app.embeddings.service import EmbeddingService


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


def test_partial_runner_startup_closes_agent_before_yielding_unavailable(
    configured_model: OpenAIResponsesModel, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_start(runner: AgentTurnRunner) -> AgentTurnRunner:
        raise RuntimeError("Runner initialization failed")

    monkeypatch.setattr(AgentTurnRunner, "__aenter__", fail_start)

    async def exercise() -> None:
        async with lifecycle.kochwiki_runner(ProviderSettings(_env_file=None)) as runner:
            assert runner is None
            assert configured_model.client.is_closed()

    asyncio.run(exercise())


def test_body_failure_propagates_and_closes_runner_and_agent(configured_model: OpenAIResponsesModel) -> None:
    async def exercise() -> None:
        with pytest.raises(LookupError, match="Application failure"):
            async with lifecycle.kochwiki_runner(ProviderSettings(_env_file=None)) as runner:
                assert runner is not None
                raise LookupError("Application failure")
        assert configured_model.client.is_closed()
        assert runner is not None
        with pytest.raises(RunnerClosedError):
            runner.create_session(owner=ApplicationIdentity("test", "user"))

    asyncio.run(exercise())


def test_later_application_startup_failure_closes_started_capabilities(
    configured_model: OpenAIResponsesModel, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = EmbeddingService(AsyncOpenAI(api_key="test-key"))
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: service)
    monkeypatch.setattr(main, "get_provider_settings", lambda: ProviderSettings(_env_file=None))

    def fail_demo() -> Agent[None, str]:
        raise RuntimeError("Demo initialization failed")

    monkeypatch.setattr(demo_lifecycle, "create_demo_agent", fail_demo)

    async def exercise() -> None:
        with pytest.raises(RuntimeError, match="Demo initialization failed"):
            async with main.AgentLifespan(FastAPI()):
                raise AssertionError("Startup should have failed")
        assert service.client is not None and service.client.is_closed()
        assert configured_model.client.is_closed()

    asyncio.run(exercise())


def test_demo_body_failure_propagates_and_closes_runner() -> None:
    async def exercise() -> None:
        owner = ApplicationIdentity("test", "user")
        with pytest.raises(LookupError, match="Application failure"):
            async with demo_lifecycle.demo_runner() as runner:
                runner.create_session(owner=owner)
                raise LookupError("Application failure")
        with pytest.raises(RunnerClosedError):
            runner.create_session(owner=owner)

    asyncio.run(exercise())
