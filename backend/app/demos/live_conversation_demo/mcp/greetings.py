from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, StringConstraints

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Language = Literal["en", "de"]


class GreetingResult(BaseModel):
    message: str
    source: Literal["greetings-mock"] = "greetings-mock"


def register_greeting_tools(server: MCPServer) -> None:
    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def greet(name: Name, language: Language) -> GreetingResult:
        """Welcome a named person in English (en) or German (de)."""
        greeting = "Hello" if language == "en" else "Hallo"
        return GreetingResult(message=f"{greeting}, {name}!")

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def farewell(name: Name, language: Language) -> GreetingResult:
        """Say goodbye to a named person in English (en) or German (de)."""
        goodbye = "Goodbye" if language == "en" else "Auf Wiedersehen"
        return GreetingResult(message=f"{goodbye}, {name}!")
