"""Pydantic AI turns, independent of the legacy execution and session models."""

from collections.abc import Callable, Sequence
from contextlib import nullcontext

from openai.types.shared import ReasoningEffort
from pydantic import SecretStr
from pydantic_ai import Agent, Tool
from pydantic_ai.capabilities import Caching, WebSearch
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import (
    MAX_MODEL_REQUESTS_PER_TURN,
    MAX_NATIVE_TOOL_CALLS_PER_RESPONSE,
    MAX_OUTPUT_TOKENS,
    MAX_TOOL_CALLS_PER_TURN,
    MODEL_REQUEST_MAX_RETRIES,
    MODEL_NETWORK_TIMEOUT_SECONDS,
    MODEL_REQUEST_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_SECONDS,
    VALIDATION_MAX_RETRIES,
)
from app.agentic.observation import TurnObservation


def create_openai_model(
    model_name: str,
    api_key: SecretStr,
    *,
    reasoning_effort: ReasoningEffort = None,
) -> OpenAIResponsesModel:
    return OpenAIResponsesModel(
        model_name,
        provider=OpenAIProvider(api_key=api_key.get_secret_value()),
        settings=OpenAIResponsesModelSettings(
            openai_store=False,
            openai_reasoning_effort=reasoning_effort,
            openai_include_web_search_sources=True,
            openai_include_raw_annotations=True,
            extra_body={"max_tool_calls": MAX_NATIVE_TOOL_CALLS_PER_RESPONSE},
        ),
    )


def create_turn_agent(
    model: Model,
    *,
    instructions: str,
    tools: Sequence[Tool[None]] = (),
    toolsets: Sequence[AbstractToolset[None]] = (),
    web_search: bool = False,
) -> Agent[None, str]:
    return Agent(
        model,
        name="conversation_turn",
        deps_type=type(None),
        output_type=str,
        instructions=instructions,
        tools=tools,
        toolsets=toolsets,
        retries=VALIDATION_MAX_RETRIES,
        tool_timeout=TOOL_TIMEOUT_SECONDS,
        model_settings={
            "max_tokens": MAX_OUTPUT_TOKENS,
            "timeout": MODEL_NETWORK_TIMEOUT_SECONDS,
            "request_timeout": MODEL_REQUEST_TIMEOUT_SECONDS,
            "max_retries": MODEL_REQUEST_MAX_RETRIES,
        },
        capabilities=[Caching(), WebSearch()] if web_search else [Caching()],
    )


async def execute_turn(
    agent: Agent[None, str],
    prompt: str,
    *,
    message_history: Sequence[ModelMessage] = (),
    usage_limits: UsageLimits | None = None,
    observation: TurnObservation | None = None,
    on_change: Callable[[], None] | None = None,
    toolsets: Sequence[AbstractToolset[None]] = (),
) -> AgentRunResult[str]:
    with observation.capture(on_change) if observation is not None else nullcontext() as hooks:
        return await agent.run(
            prompt,
            message_history=message_history,
            toolsets=toolsets,
            usage_limits=usage_limits if usage_limits is not None else UsageLimits(
                request_limit=MAX_MODEL_REQUESTS_PER_TURN,
                tool_calls_limit=MAX_TOOL_CALLS_PER_TURN,
            ),
            capabilities=[hooks] if hooks is not None else (),
        )
