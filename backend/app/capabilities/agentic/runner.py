"""Application ownership of background turns, independent of submitting callers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import aclosing
from datetime import datetime, timedelta
from types import TracebackType

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.usage import UsageLimits

from app.capabilities.agentic.config import DEFAULT_SESSION_LIFETIME, MAX_ARTIFACTS_PER_SESSION
from app.capabilities.agentic.presentation import PresentedSession, present_session
from app.capabilities.agentic.sessions import AgentSessionRegistry, SessionCreated
from app.capabilities.agentic.artifacts import ArtifactCapability
from app.core.json import FiniteJsonValue
from app.core.identity import ApplicationIdentity


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
        self._turn_tasks: set[asyncio.Task[AgentRunResult[str]]] = set()
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
        owner: ApplicationIdentity,
        initial_context: dict[str, FiniteJsonValue] | None = None,
        artifact_capabilities: Sequence[ArtifactCapability] = (),
        max_artifacts: int = MAX_ARTIFACTS_PER_SESSION,
    ) -> SessionCreated:
        if self._closed:
            raise RunnerClosedError("The turn runner is closed.")
        return self._sessions.create(
            owner=owner, initial_context=initial_context,
            artifact_capabilities=artifact_capabilities, max_artifacts=max_artifacts,
        )

    def read_session(self, session_id: str, *, owner: ApplicationIdentity) -> PresentedSession:
        """Read detached state, including settled outcomes after runner shutdown."""
        return present_session(self._sessions.read(session_id, owner=owner))

    async def observe_session(self, session_id: str, *, owner: ApplicationIdentity) -> AsyncGenerator[PresentedSession, None]:
        """Observe complete presentation snapshots until expiry, shutdown or disconnect."""
        async with aclosing(self._sessions.observe(session_id, owner=owner)) as snapshots:
            async for snapshot in snapshots:
                yield present_session(snapshot)

    async def submit(
        self,
        session_id: str,
        *,
        owner: ApplicationIdentity,
        prompt: str,
        usage_limits: UsageLimits | None = None,
        toolsets: Sequence[AbstractToolset[None]] = (),
    ) -> None:
        """Wait for admission; execution then continues under runner ownership."""
        if self._closed:
            raise RunnerClosedError("The turn runner is closed.")
        admission_future: asyncio.Future[None] = asyncio.get_running_loop().create_future()

        def admitted() -> None:
            admission_future.set_result(None)

        execution = self._sessions.execute_turn(
            session_id, owner=owner, agent=self._agent, prompt=prompt,
            usage_limits=usage_limits, toolsets=tuple(toolsets), on_admitted=admitted,
        )
        try:
            execution_task = asyncio.create_task(execution)
        except BaseException:
            execution.close()
            raise
        self._turn_tasks.add(execution_task)

        def on_execution_finished(completed_task: asyncio.Task[AgentRunResult[str]]) -> None:
            self._handle_turn_completion(completed_task, admission_future)

        execution_task.add_done_callback(on_execution_finished)
        await self._wait_for_admission(execution_task, admission_future)

    def _handle_turn_completion(
        self,
        execution_task: asyncio.Task[AgentRunResult[str]],
        admission_future: asyncio.Future[None],
    ) -> None:
        self._turn_tasks.discard(execution_task)
        if execution_task.cancelled():
            if not admission_future.done():
                admission_future.cancel()
            return
        error = execution_task.exception()
        if not admission_future.done():
            admission_future.set_exception(
                error if error is not None else RuntimeError("Turn admission was not acknowledged.")
            )
        elif error is not None and not admission_future.cancelled():
            _logger.error("Background agent turn failed (%s).", type(error).__name__)

    async def _wait_for_admission(
        self,
        execution_task: asyncio.Task[AgentRunResult[str]],
        admission_future: asyncio.Future[None],
    ) -> None:
        try:
            await asyncio.shield(admission_future)
        except asyncio.CancelledError:
            if not admission_future.done():
                admission_future.cancel()
                execution_task.cancel()
            elif not admission_future.cancelled():
                admission_future.exception()
            raise

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            for execution_task in self._turn_tasks:
                execution_task.cancel()
        pending_turns = asyncio.gather(*self._turn_tasks, return_exceptions=True)
        cancellation: asyncio.CancelledError | None = None
        while not pending_turns.done():
            try:
                await asyncio.shield(pending_turns)
            except asyncio.CancelledError as error:
                cancellation = error
        self._sessions.close_observers()
        if cancellation is not None:
            raise cancellation
