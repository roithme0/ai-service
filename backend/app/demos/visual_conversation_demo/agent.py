"""Visual Demo agent exercising messages, artifacts, and failures."""

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
FIRST_REPLY = "Hallo! Diese visuelle Demo folgt einem festen Skript. Sende noch eine Nachricht, um zu sehen, wie zwei Tool-Aufrufe Artefakte erstellen."
SECOND_REPLY = "Diese Demo hat zwei Artefakte mit Begrüßungen erstellt. Klappe die längere Liste auf, um alle zu sehen. Bei einem zusätzlichen Artefakt-Aufruf wurde absichtlich der erforderliche JSON-Wert weggelassen. Dadurch ist die Validierung fehlgeschlagen und es wurde kein Artefakt erstellt. Sende noch eine Nachricht, um einen Fehlerzustand zu sehen."
FAILED_GENERATION_UPDATE = "Ich beginne mit einer weiteren Antwort. Diese Demo bricht die Generierung nach dieser Zwischenantwort absichtlich ab. Sie bleibt ohne abschließende Antwort sichtbar."
COMPLETE_REPLY = (
    "Diese Demo ist abgeschlossen. Lade die Seite neu, um von vorn zu beginnen."
)


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

    agent.name = "visual-demo"
    return agent


def _text(content: str, phase: str) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content, provider_details={"phase": phase})])


def _artifact_step(step: int) -> ModelResponse:
    payload: dict[str, JsonValue]
    match step:
        case 0:
            commentary = "Ich erstelle zunächst eine einzelne Begrüßung."
            title = "Begrüßung"
            payload = {"value": {"message": "Hallo, Welt!"}}
        case 1:
            commentary = "Die einzelne Begrüßung ist fertig. Als Nächstes erstelle ich eine Liste mit 30 Begrüßungen, um das Aufklappen eines größeren Artefakts zu zeigen."
            title = "Begrüßungen"
            payload = {
                "value": {
                    "messages": [f"Hallo, Besucher {index}!" for index in range(1, 31)]
                }
            }
        case 2:
            commentary = "Beide Artefakte sind fertig. Ich lasse jetzt absichtlich den erforderlichen JSON-Wert weg, um zu zeigen, wie ein fehlgeschlagener Tool-Aufruf dargestellt wird."
            title = "Begrüßung"
            payload = {}
        case _:
            return _text(SECOND_REPLY, "final_answer")
    return ModelResponse(
        parts=[
            TextPart(commentary, provider_details={"phase": "commentary"}),
            ToolCallPart(
                "present_artifact",
                {"type": "json", "content": {"title": title, "payload": payload}},
                f"visual-demo-artifact-{step}",
            ),
        ]
    )
