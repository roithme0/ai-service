"""Provider-neutral completed message validation and answer selection."""

from typing import cast

from app.agents.models.generation import AgenticGenerationResponse, AgenticInputItem, AssistantMessagePhase
from app.sessions.limits import MAX_MESSAGE_LENGTH


def message_phase(item: AgenticInputItem) -> AssistantMessagePhase | None:
    phase = item.get("phase")
    if phase == "commentary":
        return "commentary"
    if phase == "final_answer":
        return "final_answer"
    return None


def final_response_text(response: AgenticGenerationResponse) -> str | None:
    return next((message_text(item) for item in response.output_items
                 if item.get("type") == "message" and message_phase(item) == "final_answer"), None)


def message_text(item: AgenticInputItem) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in cast(list[object], content):
            if isinstance(part, dict):
                text = cast(dict[str, object], part).get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "".join(texts)
    return ""


def validate_message_item(item: AgenticInputItem) -> None:
    if item.get("type") == "message":
        text = message_text(item)
        if not text.strip() or len(text) > MAX_MESSAGE_LENGTH:
            raise ValueError("assistant message must be nonblank and within the message length limit")
