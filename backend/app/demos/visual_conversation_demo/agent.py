"""Visual Conversation Demo agent exercising messages, artifacts, and failures."""

import asyncio

from pydantic import JsonValue
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.turns import create_turn_agent

TURN_DELAY_SECONDS = 1.5
FIRST_REPLY = "Hello! This is a scripted chat UI demo. Send another message to see two tools create artifacts."
SECOND_REPLY = "This scripted demo created two greetings artifacts. Expand the longer list to see them all. An additional artifact call deliberately omitted the required JSON value and failed validation, so it created no artifact. Send another message to see an error state."
FAILED_GENERATION_UPDATE = "I'll start another response. This demo will deliberately stop generation after this update, leaving it visible without a final answer."
COMPLETE_REPLY = "This scripted demo is complete. Refresh the page to restart it."


def create_visual_conversation_demo_agent(
    *, delay_seconds: float = TURN_DELAY_SECONDS
) -> Agent[None, str]:
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(delay_seconds)
        prompts = [
            index
            for index, message in enumerate(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart) and isinstance(part.content, str)
        ]
        turn = len(prompts)
        responses = [
            message
            for message in messages[prompts[-1] :]
            if isinstance(message, ModelResponse)
        ]
        match turn:
            case 1:
                return _text(FIRST_REPLY, "final_answer")
            case 2:
                return _artifact_step(len(responses))
            case 3:
                return _text(FAILED_GENERATION_UPDATE, "commentary")
            case _:
                return _text(COMPLETE_REPLY, "final_answer")

    agent = create_turn_agent(
        FunctionModel(respond), instructions="Follow the deterministic demo script."
    )

    @agent.output_validator
    async def validate_output(ctx: RunContext[None], output: str) -> str:
        if output == FAILED_GENERATION_UPDATE:
            await asyncio.sleep(delay_seconds)
            raise RuntimeError("Scripted demo generation failure")
        return output

    agent.name = "demo"
    return agent


def _text(content: str, phase: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content, provider_details={"phase": phase})])


def _artifact_step(step: int) -> ModelResponse:
    payload: dict[str, JsonValue]
    match step:
        case 0:
            commentary = "I'll create a single greeting first."
            title = "demo.greeting"
            payload = {"value": {"message": "Hello, World!"}}
        case 1:
            commentary = "The single greeting is ready. Next I'll create a list of 30 greetings to demonstrate expanding a larger artifact."
            title = "demo.greetings"
            payload = {
                "value": {
                    "messages": [f"Hello, Visitor {index}!" for index in range(1, 31)]
                }
            }
        case 2:
            commentary = "Both artifacts are ready. I'll now deliberately omit the required JSON value to show how a failed tool call appears."
            title = "demo.greeting"
            payload = {}
        case _:
            return _text(SECOND_REPLY, "final_answer")
    return ModelResponse(
        parts=[
            TextPart(commentary, provider_details={"phase": "commentary"}),
            ToolCallPart(
                "present_artifact",
                {"type": "json", "content": {"title": title, "payload": payload}},
                f"demo-artifact-{step}",
            ),
        ]
    )
