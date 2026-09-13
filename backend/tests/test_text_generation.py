import asyncio

import pytest

from app.models.text_generation import (
    MAX_CONTEXT_LENGTH,
    MAX_INSTRUCTIONS_LENGTH,
    TextGenerationRequest,
    TextGenerationResponse,
    generate_text,
)
from app.sessions.text_sessions import MAX_MESSAGE_COUNT, MAX_MESSAGE_LENGTH, TextMessage


class FakeGenerator:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[TextGenerationRequest] = []

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        self.calls.append(request)
        return TextGenerationResponse(text=self.response)


def test_passes_ordered_conversation_to_generator_and_returns_one_response() -> None:
    request = TextGenerationRequest(
        messages=(TextMessage("user", "  Hello  "), TextMessage("assistant", "Hi"))
    )
    generator = FakeGenerator("  Answer  ")

    response = asyncio.run(generate_text(generator, request))

    assert generator.calls == [request]
    assert response == TextGenerationResponse(text="  Answer  ")


@pytest.mark.parametrize(
    "messages",
    [
        (),
        (TextMessage("user", "hello"),) * (MAX_MESSAGE_COUNT + 1),
        (TextMessage("user", "  "),),
        (TextMessage("user", "x" * (MAX_MESSAGE_LENGTH + 1)),),
    ],
)
def test_invalid_conversation_never_reaches_generator(
    messages: tuple[TextMessage, ...],
) -> None:
    generator = FakeGenerator("answer")

    with pytest.raises(ValueError):
        asyncio.run(generate_text(generator, TextGenerationRequest(messages)))

    assert generator.calls == []


@pytest.mark.parametrize("context", ["", " \t "])
def test_blank_context_is_allowed(context: str) -> None:
    request = TextGenerationRequest((TextMessage("user", "hi"),), context=context)
    generator = FakeGenerator("answer")

    assert asyncio.run(generate_text(generator, request)) == TextGenerationResponse("answer")
    assert generator.calls == [request]


def test_oversized_context_never_reaches_generator() -> None:
    generator = FakeGenerator("answer")
    request = TextGenerationRequest(
        (TextMessage("user", "hi"),), context="x" * (MAX_CONTEXT_LENGTH + 1)
    )

    with pytest.raises(ValueError, match="context exceeds"):
        asyncio.run(generate_text(generator, request))

    assert generator.calls == []


def test_oversized_instructions_never_reach_generator() -> None:
    generator = FakeGenerator("answer")
    request = TextGenerationRequest(
        (TextMessage("user", "hi"),), instructions="x" * (MAX_INSTRUCTIONS_LENGTH + 1)
    )

    with pytest.raises(ValueError, match="instructions exceed"):
        asyncio.run(generate_text(generator, request))

    assert generator.calls == []


@pytest.mark.parametrize("response", ["  ", "x" * (MAX_MESSAGE_LENGTH + 1)])
def test_invalid_generator_output_is_rejected(response: str) -> None:
    generator = FakeGenerator(response)

    with pytest.raises(ValueError):
        asyncio.run(generate_text(generator, TextGenerationRequest((TextMessage("user", "hi"),))))

    assert len(generator.calls) == 1
