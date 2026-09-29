from types import TracebackType

from fastapi import FastAPI
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.agents.wiring import get_configured_agents
from app.sessions.http import ErrorResponse, router as conversation_router


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


app = FastAPI(
    title="AI Service",
    lifespan=AgentLifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(conversation_router)


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, error: StarletteHTTPException) -> Response:
    if error.status_code == 404:
        body = ErrorResponse(detail="Not Found", kind="not_found")
        return JSONResponse(status_code=404, content=body.model_dump(mode="json", exclude_none=True), headers=error.headers)
    return await http_exception_handler(request, error)


@app.get("/")
async def hello_world() -> dict[str, str]:
    return {"message": "Hello World"}
