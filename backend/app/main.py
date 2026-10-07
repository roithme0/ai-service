from types import TracebackType

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.agents.wiring import get_configured_agents
from app.core.http import router as core_router
from app.core.models import HttpErrorResponse, RequestValidationErrorResponse, ValidationDetail
from app.sessions.http import router as conversation_router


class AgentLifespan:
    def __init__(self, _application: FastAPI) -> None:
        self._agents = get_configured_agents()

    async def __aenter__(self) -> None:
        await self._agents.start()

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
app.include_router(conversation_router, responses={
    405: {"model": HttpErrorResponse},
    500: {"model": HttpErrorResponse},
})
app.include_router(core_router, responses={
    405: {"model": HttpErrorResponse},
    500: {"model": HttpErrorResponse},
})


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(_request: Request, error: StarletteHTTPException) -> JSONResponse:
    if error.status_code == 404:
        body = HttpErrorResponse(detail="Not Found", kind="not_found")
    elif error.status_code == 405:
        body = HttpErrorResponse(detail="Method Not Allowed", kind="method_not_allowed")
    elif error.status_code >= 500:
        body = HttpErrorResponse(detail="Internal Server Error", kind="internal_error")
    else:
        detail = error.detail if isinstance(error.detail, str) and error.detail else "HTTP error"
        body = HttpErrorResponse(detail=detail, kind="http_error")
    return JSONResponse(
        status_code=error.status_code, content=body.model_dump(mode="json", exclude_none=True), headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation(_request: Request, error: RequestValidationError) -> JSONResponse:
    body = RequestValidationErrorResponse(
        detail=[ValidationDetail(loc=tuple(issue["loc"]), msg=issue["msg"], type=issue["type"])
                for issue in error.errors()],
        kind="request_validation",
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.exception_handler(Exception)
async def handle_unexpected_exception(_request: Request, _error: Exception) -> JSONResponse:
    body = HttpErrorResponse(detail="Internal Server Error", kind="internal_error")
    return JSONResponse(status_code=500, content=body.model_dump(mode="json", exclude_none=True))
