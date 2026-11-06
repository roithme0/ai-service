from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app.demos.live_conversation_demo.mcp.greetings import register_greeting_tools
from app.demos.live_conversation_demo.mcp.instructions import GREETINGS_INSTRUCTIONS
from app.demos.live_conversation_demo.mcp.resources import register_greeting_resources


def create_mcp_server() -> tuple[MCPServer, Starlette]:
    server = MCPServer("Greetings", instructions=GREETINGS_INSTRUCTIONS)
    register_greeting_tools(server)
    register_greeting_resources(server)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[
                "localhost",
                "localhost:*",
                "127.0.0.1",
                "127.0.0.1:*",
                "[::1]",
                "[::1]:*",
            ],
        ),
    )
    return server, mcp_app
