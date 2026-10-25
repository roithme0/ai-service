import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from types import TracebackType

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.capabilities.conversations.http import create_session_router
from app.capabilities.conversations.lifecycle import kochwiki_runner
from app.capabilities.conversations.runner import AgentTurnRunner
from app.core.config import get_provider_settings
from app.core.models import HttpErrorResponse, RequestValidationErrorResponse, ValidationDetail
from app.demos.visual_conversation_demo.lifecycle import visual_conversation_demo_runner
from app.capabilities.embeddings.http import router as embedding_router
from app.capabilities.embeddings.lifecycle import embedding_service


class AgentLifespan:
    def __init__(self, application: FastAPI) -> None:
        self._configure_logging()
        self._runners: dict[str, AgentTurnRunner | None] = {"kochwiki": None, "demo": None}
        application.state.agent_runners = self._runners
        self._resource_stack = AsyncExitStack()
        self._application = application

    @staticmethod
    def _configure_logging() -> None:
        application_logger = logging.getLogger("app")
        if application_logger.level == logging.NOTSET:
            application_logger.setLevel(logging.INFO)
        if not application_logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            application_logger.addHandler(handler)

    async def __aenter__(self) -> None:
        try:
            provider_settings = get_provider_settings()
            self._application.state.embedding_service = await self._resource_stack.enter_async_context(
                embedding_service(provider_settings),
            )
            self._runners["kochwiki"] = await self._resource_stack.enter_async_context(kochwiki_runner(provider_settings))
            self._runners["demo"] = await self._resource_stack.enter_async_context(visual_conversation_demo_runner())
        except BaseException:
            await self._resource_stack.aclose()
            raise

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._runners["kochwiki"] = None
        self._runners["demo"] = None
        await self._resource_stack.aclose()


def get_agent_registry(request: Request) -> Mapping[str, AgentTurnRunner | None]:
    return request.app.state.agent_runners


app = FastAPI(
    title="AI Service",
    lifespan=AgentLifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(create_session_router(get_agent_registry), responses={
    405: {"model": HttpErrorResponse},
    500: {"model": HttpErrorResponse},
})
app.include_router(embedding_router)


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
