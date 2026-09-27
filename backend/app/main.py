from types import TracebackType

from fastapi import FastAPI

from app.agents.wiring import get_configured_agents
from app.sessions.http import router as conversation_router


class AgentLifespan:
    def __init__(self, _application: FastAPI) -> None:
        self._agents = get_configured_agents()

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        try:
            await self._agents.close()
        finally:
            get_configured_agents.cache_clear()


app = FastAPI(title="AI Service", lifespan=AgentLifespan)
app.include_router(conversation_router)

@app.get("/")
async def hello_world() -> dict[str, str]:
    return {"message": "Hello World"}
