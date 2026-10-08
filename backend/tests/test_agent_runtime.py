import asyncio

import pytest

from app.agents.runtime import AgentRuntime
from app.agents.enums.runtime import RuntimeStatus
from app.mcp.connection import MCPConnection
from runtime_wait import wait_for_status


class RecordedConnection(MCPConnection):
    def __init__(self, name: str, events: list[str], *, fail_start: bool = False, fail_close: bool = False) -> None:
        super().__init__(name, "http://localhost/mcp/")
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close

    async def start(self) -> None:
        self.events.append(f"start {self.name}")
        if self.fail_start:
            raise ConnectionError("unavailable")

    async def close(self) -> None:
        self.events.append(f"close {self.name}")
        if self.fail_close:
            raise RuntimeError("cleanup failed")


class RecordedModelClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("close model")


def test_partial_start_failure_retains_healthy_connection_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        events: list[str] = []
        failing = RecordedConnection("second", events, fail_start=True)
        runtime = AgentRuntime(
            "test", object(), model_client=RecordedModelClient(events),
            mcp_connections=(RecordedConnection("first", events), failing),
        )
        monkeypatch.setattr("app.mcp.config.INITIAL_RETRY_SECONDS", 0.01)
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            assert runtime.agent is not None
            assert runtime.issue is not None and runtime.issue.retryable
            assert runtime.issue.connection == "second"
            assert events == ["start first", "start second"]
            failing.fail_start = False
            await wait_for_status(runtime, RuntimeStatus.READY)
            assert runtime.issue is None
            assert events == ["start first", "start second", "start second"]
        finally:
            await runtime.close()
        assert runtime.status == RuntimeStatus.CLOSED
        assert events[-3:] == ["close second", "close first", "close model"]
        await runtime.close()
        assert len(events) == 6

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
        await wait_for_status(runtime, RuntimeStatus.READY)
        with pytest.raises(RuntimeError, match="cleanup failed"):
            await runtime.close()
        assert runtime.agent is None
        assert runtime.status == RuntimeStatus.CLOSED
        assert events == ["start first", "start second", "close second", "close first", "close model"]
        await runtime.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("during_attempt", [False, True])
def test_shutdown_interrupts_attempt_or_retry_wait(during_attempt: bool) -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        settled = asyncio.Event()
        events: list[str] = []

        class PendingConnection(RecordedConnection):
            async def start(self) -> None:
                entered.set()
                try:
                    if during_attempt:
                        await asyncio.Event().wait()
                    raise ConnectionError("offline")
                finally:
                    settled.set()

        runtime = AgentRuntime("test", object(), mcp_connections=(PendingConnection("pending", events),))
        await runtime.start()
        assert runtime.status == RuntimeStatus.CONNECTING
        try:
            await asyncio.wait_for(entered.wait(), 2)
            if not during_attempt:
                await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
        finally:
            await asyncio.wait_for(runtime.close(), 2)
        assert settled.is_set()
        assert runtime.status == RuntimeStatus.CLOSED
        assert events == ["close pending"]

    asyncio.run(exercise())


def test_unknown_initialization_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def exercise() -> None:
        events: list[str] = []

        class BrokenConnection(RecordedConnection):
            async def start(self) -> None:
                events.append("attempt")
                raise RuntimeError("bug")

        monkeypatch.setattr("app.mcp.config.INITIAL_RETRY_SECONDS", 0.001)
        runtime = AgentRuntime("test", object(), mcp_connections=(BrokenConnection("broken", events),))
        await runtime.start()
        try:
            await wait_for_status(runtime, RuntimeStatus.UNAVAILABLE)
            await asyncio.sleep(0.01)
            assert events == ["attempt"]
            assert runtime.issue is not None and not runtime.issue.retryable
        finally:
            await runtime.close()

    asyncio.run(exercise())


def test_missing_configuration_starts_no_connection_attempt() -> None:
    async def exercise() -> None:
        events: list[str] = []
        runtime: AgentRuntime[object] = AgentRuntime("test", None, mcp_connections=(RecordedConnection("unused", events),))
        await runtime.start()
        assert runtime.status == RuntimeStatus.UNAVAILABLE
        assert runtime.issue is not None and runtime.issue.kind == "configuration"
        assert events == []
        await runtime.close()

    asyncio.run(exercise())
