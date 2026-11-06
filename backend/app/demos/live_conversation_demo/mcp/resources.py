"""Static greeting reference data exposed as an MCP resource."""

import json

from mcp.server import MCPServer


def register_greeting_resources(server: MCPServer) -> None:
    @server.resource(
        "greetings://catalog",
        name="Greeting catalog",
        description="Supported greeting languages, vocabulary, and greeting club motto.",
        mime_type="application/json",
    )
    def read_catalog() -> str:
        return json.dumps(
            {
                "languages": {
                    "en": {"greet": "Hello", "farewell": "Goodbye"},
                    "de": {"greet": "Hallo", "farewell": "Auf Wiedersehen"},
                },
                "motto": "Every hello starts an adventure.",
            }
        )
