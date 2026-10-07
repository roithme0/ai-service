"""Provider-neutral generation interface."""

from typing import Protocol

from app.agents.models.generation import AgenticGenerationRequest, AgenticGenerationResponse


class AgenticGenerator(Protocol):
    async def generate(self, request: AgenticGenerationRequest) -> AgenticGenerationResponse: ...
