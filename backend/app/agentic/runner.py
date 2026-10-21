"""Application ownership of background turns, independent of submitting callers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import aclosing
from datetime import datetime, timedelta
from types import TracebackType

from pydantic import JsonValue
from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.agentic.config import DEFAULT_SESSION_LIFETIME, MAX_ARTIFACTS
from app.agentic.presentation import PresentedSession, present_session
from app.agentic.sessions import AgentSessionRegistry, SessionCreated
from app.agentic.artifact_models import ArtifactCapability


_logger = logging.getLogger(__name__)


class RunnerClosedError(RuntimeError):
    """The runner has stopped accepting new sessions and turns."""


class AgentTurnRunner:
    """Consumer boundary for one agent and its private session registry.

    Use on one event loop, inside the shared agent's native async context.
    """

    def __init__(
        self,
        agent: Agent[None, str],
        *,
        session_lifetime: timedelta = DEFAULT_SESSION_LIFETIME,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._agent = agent
        self._sessions = AgentSessionRegistry(lifetime=session_lifetime, clock=clock)
        self._tasks: set[asyncio.Task[AgentRunResult[str]]] = set()
        self._closed = False

    async def __aenter__(self) -> AgentTurnRunner:
        if self._closed:
            raise RunnerClosedError("The turn runner is closed.")
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.close()

    def create_session(
        self,
        *,
        owner: str,
        initial_context: dict[str, JsonValue] | None = None,
        artifact_capabilities: Sequence[ArtifactCapability] = (),
        max_artifacts: int = MAX_ARTIFACTS,
    ) -> SessionCreated:
        if self._closed:
            raise RunnerClosedError("The turn runner is closed.")
        return self._sessions.create(
            owner=owner, initial_context=initial_context,
            artifact_capabilities=artifact_capabilities, max_artifacts=max_artifacts,
        )

    def read_session(self, session_id: str, *, owner: str) -> PresentedSession:
        """Read detached state, including settled outcomes after runner shutdown."""
        return present_session(self._sessions.read(session_id, owner=owner))

    async def observe_session(self, session_id: str, *, owner: str) -> AsyncGenerator[PresentedSession, None]:
        """Observe complete presentation snapshots until expiry, shutdown or disconnect."""
        async with aclosing(self._sessions.observe(session_id, owner=owner)) as snapshots:
            async for snapshot in snapshots:
                yield present_session(snapshot)

    async def submit(
        self,
        session_id: str,
        *,
        owner: str,
        prompt: str,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
    ) -> None:
        """Wait for admission; execution then continues under runner ownership."""
        if self._closed:
            raise RunnerClosedError("The turn runner is closed.")
        admission: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def admitted() -> None:
            admission.set_result(None)

        execution = self._sessions.execute_turn(
            session_id, owner=owner, agent=self._agent, prompt=prompt,
            usage_limits=usage_limits, toolsets=tuple(toolsets), on_admitted=admitted,
        )
        try:
            task = asyncio.create_task(execution)
        except BaseException:
            execution.close()
            raise
        self._tasks.add(task)

        def finished(completed: asyncio.Task[AgentRunResult[str]]) -> None:
            self._tasks.discard(completed)
            if completed.cancelled():
                if not admission.done():
                    admission.cancel()
                return
            error = completed.exception()
            if not admission.done():
                admission.set_exception(error if error is not None else RuntimeError("Turn admission was not acknowledged."))
            elif error is not None and not admission.cancelled():
                _logger.error("Background agent turn failed (%s).", type(error).__name__)

        task.add_done_callback(finished)
        try:
            await asyncio.shield(admission)
        except asyncio.CancelledError:
            if not admission.done():
                admission.cancel()
                task.cancel()
            elif not admission.cancelled():
                admission.exception()
            raise

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            for task in self._tasks:
                task.cancel()
        completion = asyncio.gather(*self._tasks, return_exceptions=True)
        cancellation: asyncio.CancelledError | None = None
        while not completion.done():
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError as error:
                cancellation = error
        self._sessions.close_observers()
        if cancellation is not None:
            raise cancellation
