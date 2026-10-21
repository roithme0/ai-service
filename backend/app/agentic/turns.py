"""Native agent construction and conversation execution."""

from collections.abc import Callable, Sequence
from contextlib import nullcontext

from openai.types.shared import ReasoningEffort
from pydantic import SecretStr
from pydantic_ai import Agent, Conversation, Tool
from pydantic_ai.capabilities import Caching, WebSearch
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import (
    MAX_NATIVE_TOOL_CALLS_PER_RESPONSE,
    MAX_OUTPUT_TOKENS,
    MODEL_REQUEST_MAX_RETRIES,
    MODEL_NETWORK_TIMEOUT_SECONDS,
    MODEL_REQUEST_TIMEOUT_SECONDS,
    TOOL_TIMEOUT_SECONDS,
    VALIDATION_MAX_RETRIES,
)
from app.agentic.observation import TurnObservation
from app.agentic.limits import turn_usage_limits


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
    conversation: Conversation | None = None,
    usage_limits: UsageLimits | None = None,
    observation: TurnObservation | None = None,
    on_change: Callable[[], None] | None = None,
    toolsets: Sequence[AbstractToolset[None]] = (),
) -> AgentRunResult[str]:
    state = conversation if conversation is not None else Conversation()
    limits = turn_usage_limits(state.usage, usage_limits)
    with observation.capture(on_change) if observation is not None else nullcontext() as hooks:
        return await agent.run(
            prompt,
            conversation=state,
            toolsets=toolsets,
            usage_limits=limits,
            capabilities=[hooks] if hooks is not None else (),
        )
