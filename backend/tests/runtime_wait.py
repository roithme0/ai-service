import asyncio
from typing import Protocol

from app.agents.enums.runtime import RuntimeStatus


class RuntimeState(Protocol):
    @property
    def status(self) -> RuntimeStatus: ...


async def wait_for_status(runtime: RuntimeState, status: RuntimeStatus) -> None:
    async with asyncio.timeout(2):
        while runtime.status != status:
            await asyncio.sleep(0)
