import asyncio

import pytest

from app.agents.runtime import AgentRuntime
from app.mcp_connection import MCPConnection


class RecordedConnection(MCPConnection):
    def __init__(self, name: str, events: list[str], *, fail_start: bool = False, fail_close: bool = False) -> None:
        super().__init__(name, "http://localhost/mcp/")
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self) -> None:
        self.events.append(f"start {self.name}")
        if self.fail_start:
            raise RuntimeError("unavailable")

    async def close(self) -> None:
        self.events.append(f"close {self.name}")
        if self.fail_close:
            raise RuntimeError("cleanup failed")


class RecordedModelClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("close model")


def test_partial_start_failure_closes_all_owned_resources_once() -> None:
    async def exercise() -> None:
        events: list[str] = []
        runtime = AgentRuntime(
            "test", object(), model_client=RecordedModelClient(events),
            mcp_connections=(RecordedConnection("first", events), RecordedConnection("second", events, fail_start=True)),
        )
        await runtime.start()
        assert runtime.agent is None
        assert events == ["start first", "start second", "close second", "close first", "close model"]
        await runtime.close()
        assert len(events) == 5

    asyncio.run(exercise())


def test_shutdown_attempts_every_cleanup_even_if_one_fails() -> None:
    async def exercise() -> None:
        events: list[str] = []
        runtime = AgentRuntime(
            "test", object(), model_client=RecordedModelClient(events),
            mcp_connections=(RecordedConnection("first", events), RecordedConnection("second", events, fail_close=True)),
        )
        await runtime.start()
        await runtime.start()
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await runtime.close()
        assert runtime.agent is None
        assert events == ["start first", "start second", "close second", "close first", "close model"]
        await runtime.close()

    asyncio.run(exercise())
