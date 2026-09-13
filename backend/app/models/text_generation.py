"""Bounded, provider-neutral text generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.sessions.text_sessions import MAX_MESSAGE_COUNT, MAX_MESSAGE_LENGTH, TextMessage


@dataclass(frozen=True)
class TextGenerationRequest:
    messages: tuple[TextMessage, ...]


@dataclass(frozen=True)
class TextGenerationResponse:
    text: str


class TextGenerator(Protocol):
    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse: ...


async def generate_text(
    generator: TextGenerator, request: TextGenerationRequest
) -> TextGenerationResponse:
    if not request.messages or len(request.messages) > MAX_MESSAGE_COUNT:
        raise ValueError("conversation must contain 1 to 100 messages")
    if any(
        message.role not in ("user", "assistant")
        or not isinstance(message.text, str)
        or not message.text.strip()
        or len(message.text) > MAX_MESSAGE_LENGTH
        for message in request.messages
    ):
        raise ValueError("conversation contains an invalid message")

    response = await generator.generate(request)
    if not isinstance(response.text, str) or not response.text.strip():
        raise ValueError("generator returned blank text")
    if len(response.text) > MAX_MESSAGE_LENGTH:
        raise ValueError("generator returned text exceeding the message limit")
    return response
