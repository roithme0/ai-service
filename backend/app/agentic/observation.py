"""Per-turn inspection using native messages and execution hooks, without streaming."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field

from pydantic_ai import RunContext, ToolDefinition
from pydantic_ai.capabilities import AgentNode, Hooks, ValidatedToolArgs
from pydantic_ai.messages import ModelMessage, ToolCallPart
from pydantic_ai.usage import RunUsage


@dataclass
class TurnObservation:
    """Single-use capture. Messages and usage settle even when execution raises."""

    messages: list[ModelMessage] = field(default_factory=list, init=False)
    started_calls: tuple[ToolCallPart, ...] = field(default=(), init=False)
    usage: RunUsage = field(default_factory=RunUsage, init=False)
    run_id: str | None = field(default=None, init=False)
    conversation_id: str | None = field(default=None, init=False)
    _used: bool = field(default=False, init=False, repr=False)

    @contextmanager
    def capture(self) -> Iterator[Hooks[None]]:
        if self._used:
            raise ValueError("Use a new TurnObservation for each turn.")
        self._used = True
        history: list[ModelMessage] = []
        usage = RunUsage()
        hooks = Hooks[None]()

        @hooks.on.before_node_run
        def observe_node(ctx: RunContext[None], *, node: AgentNode[None]) -> AgentNode[None]:
            nonlocal history, usage
            history = ctx.messages
            usage = ctx.usage
            self.run_id = ctx.run_id
            self.conversation_id = ctx.conversation_id
            return node

        @hooks.on.before_tool_execute
        def start_tool(
            ctx: RunContext[None],
            *,
            call: ToolCallPart,
            tool_def: ToolDefinition,
            args: ValidatedToolArgs,
        ) -> ValidatedToolArgs:
            self.started_calls += (deepcopy(call),)
            return args

        try:
            yield hooks
        finally:
            self.messages = deepcopy(history)
            self.usage = deepcopy(usage)
