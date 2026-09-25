from types import TracebackType

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agents.wiring import get_configured_agents
from app.recipe_improvement.http import AgentUnavailable, router as recipe_improvement_router


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
app.include_router(recipe_improvement_router)


@app.exception_handler(AgentUnavailable)
async def agent_unavailable(request: Request, error: AgentUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"kind": "agent_unavailable"})

@app.get("/")
async def hello_world() -> dict[str, str]:
    return {"message": "Hello World"}
