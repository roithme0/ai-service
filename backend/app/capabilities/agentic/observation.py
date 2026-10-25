"""Per-turn inspection using native messages and execution hooks, without streaming."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field

from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.capabilities import AgentNode, Hooks, NodeResult, ValidatedToolArgs
from pydantic_ai.messages import ModelMessage, ToolCallPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.usage import RunUsage


@dataclass
class TurnObservation:
    """Single-use view of native execution state.

    Messages and usage reference Pydantic AI's live state during capture.
    Usage includes the native conversation baseline when continuing a conversation.
    Both become detached copies when capture ends, including on failure or cancellation.
    """

    messages: list[ModelMessage] = field(default_factory=list, init=False)
    started_tool_calls: tuple[ToolCallPart, ...] = field(default=(), init=False)
    usage: RunUsage = field(default_factory=RunUsage, init=False)
    run_id: str | None = field(default=None, init=False)
    conversation_id: str | None = field(default=None, init=False)
    _used: bool = field(default=False, init=False, repr=False)

    @contextmanager
    def capture(self, on_change: Callable[[], None] | None = None) -> Iterator[Hooks[None]]:
        if self._used:
            raise ValueError("Use a new TurnObservation for each turn.")
        self._used = True
        hooks = Hooks[None]()

        def observe(ctx: RunContext[None]) -> None:
            self.messages = ctx.messages
            self.usage = ctx.usage
            self.run_id = ctx.run_id
            self.conversation_id = ctx.conversation_id
            if on_change is not None:
                on_change()

        @hooks.on.before_node_run
        async def observe_node(ctx: RunContext[None], *, node: AgentNode[None]) -> AgentNode[None]:
            observe(ctx)
            return node

        @hooks.on.after_node_run
        async def observe_completed_node(
            ctx: RunContext[None], *, node: AgentNode[None], result: NodeResult[None],
        ) -> NodeResult[None]:
            observe(ctx)
            return result

        @hooks.on.before_model_request
        async def observe_request(
            ctx: RunContext[None], request_context: ModelRequestContext,
        ) -> ModelRequestContext:
            observe(ctx)
            return request_context

        @hooks.on.before_tool_execute
        async def start_tool(
            ctx: RunContext[None],
            *,
            call: ToolCallPart,
            tool_def: ToolDefinition,
            args: ValidatedToolArgs,
        ) -> ValidatedToolArgs:
            self.started_tool_calls += (deepcopy(call),)
            observe(ctx)
            return args

        try:
            yield hooks
        finally:
            self.messages = deepcopy(self.messages)
            self.usage = deepcopy(self.usage)
