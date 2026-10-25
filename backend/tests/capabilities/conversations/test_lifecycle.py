import asyncio

import pytest
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel

from app.capabilities.conversations import lifecycle
from app.capabilities.conversations.config import KochwikiConversationSettings
from app.capabilities.conversations.runner import AgentTurnRunner, RunnerClosedError
from app.capabilities.conversations.turns import create_openai_model
from app.core.config import ProviderSettings
from app.core.identity import ApplicationIdentity


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
