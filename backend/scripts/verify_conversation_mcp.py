"""Exercise one explicitly read-only MCP tool and a native-history follow-up."""

import argparse
import asyncio

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from app.capabilities.conversations.config import MAX_MODEL_REQUESTS_PER_TURN
from app.capabilities.conversations.mcp import create_mcp_toolset
from app.capabilities.conversations.turns import create_openai_model, create_turn_agent, execute_turn
from app.core.config import ProviderSettings
from app.capabilities.conversations.config import KochwikiConversationSettings


async def verify(tool_name: str, prompt: str) -> None:
    settings = KochwikiConversationSettings()
    provider_settings = ProviderSettings()
    if (
        provider_settings.openai_api_key is None
        or settings.kochwiki_openai_model is None
        or settings.kochwiki_mcp_url is None
    ):
        raise SystemExit("Set OPENAI_API_KEY, KOCHWIKI_OPENAI_MODEL and KOCHWIKI_MCP_URL in backend/.env.")

    toolset = create_mcp_toolset(settings.kochwiki_mcp_url, id="kochwiki")

    def allow_selected_tool(ctx: RunContext[None], tool: ToolDefinition) -> bool:
        return tool.name == tool_name

    async with toolset:
        tools = await toolset.client.list_tools()
        selected = next((tool for tool in tools if tool.name == tool_name), None)
        if selected is None or selected.annotations is None or selected.annotations.read_only_hint is not True:
            raise SystemExit("Choose an existing tool explicitly advertised by the server as read-only.")

        agent = create_turn_agent(
            create_openai_model(
                settings.kochwiki_openai_model,
                provider_settings.openai_api_key,
                reasoning_effort=settings.kochwiki_openai_reasoning_effort,
            ),
            instructions=(
                "Use the available read-only tool when fresh domain information is needed. "
                "Use its returned information in your answer and report failures accurately. "
                "Reuse previous results for follow-up questions."
            ),
            toolsets=[toolset.filtered(allow_selected_tool)],
        )
        async with agent:
            first = await execute_turn(
                agent, f"Use the tool exactly once to answer this question: {prompt}",
                usage_limits=UsageLimits(request_limit=MAX_MODEL_REQUESTS_PER_TURN, tool_calls_limit=1),
            )
            results = [
                part for message in first.new_messages() for part in message.parts
                if isinstance(part, ToolReturnPart)
            ]
            assert len(results) == 1 and results[0].outcome == "success", "Expected one successful MCP result."
            second = await execute_turn(
                agent, "Summarize the information you just retrieved without calling a tool.",
                conversation=first.conversation,
                usage_limits=UsageLimits(request_limit=MAX_MODEL_REQUESTS_PER_TURN, tool_calls_limit=0),
            )
            assert first.output.strip() and second.output.strip(), "Expected answers in both turns."

    for number, result in enumerate((first, second), start=1):
        print(f"Turn {number}: {result.output}")
        print(f"  Cumulative usage: {result.usage}")
    print("Verified one successful MCP call and a follow-up without another tool execution.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, help="Exact MCP tool name, advertised as read-only.")
    parser.add_argument("--prompt", required=True, help="A read-only question answerable with one call to that tool.")
    args = parser.parse_args()
    asyncio.run(verify(args.tool, args.prompt))
