"""Small SSE transport primitives shared by capabilities."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import TypeVar

from anyio import CancelScope
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

T = TypeVar("T")
HEARTBEAT_INTERVAL_SECONDS = 15.0


def frame(value: BaseModel) -> str:
    return f"data: {value.model_dump_json()}\n\n"


async def with_heartbeats(
    updates: AsyncGenerator[T, None], interval: float = HEARTBEAT_INTERVAL_SECONDS
) -> AsyncGenerator[T | None, None]:
    pending: asyncio.Task[T] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(updates))
            done, _ = await asyncio.wait((pending,), timeout=interval)
            if not done:
                yield None
                continue
            value = pending.result()
            pending = None
            yield value
    except StopAsyncIteration:
        return
    finally:
        with CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending
            await updates.aclose()


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"

    def __init__(
        self,
        events: AsyncGenerator[str, None],
        updates: AsyncGenerator[object, None],
        cache: str,
        status_code: int = 200,
    ) -> None:
        self.events = events
        self.updates = updates
        super().__init__(
            events,
            status_code=status_code,
            media_type=self.media_type,
            headers={"Cache-Control": cache, "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with CancelScope(shield=True):
                await self.events.aclose()
                await self.updates.aclose()
