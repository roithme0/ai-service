from collections.abc import Mapping
from functools import partial

from fastapi import FastAPI, Request

from app.capabilities.conversations.http import create_session_router
from app.capabilities.conversations.runner import AgentTurnRunner
from app.capabilities.embeddings.http import router as embedding_router
from app.capabilities.transcriptions.http import router as transcription_router
from app.core.http import register_error_handlers
from app.core.models import HttpErrorResponse
from app.demos.live_conversation_demo.mcp.server import create_mcp_server
from app.lifespan import application_lifespan


def get_agent_registry(request: Request) -> Mapping[str, AgentTurnRunner | None]:
    return request.app.state.agent_runners


def create_app() -> FastAPI:
    mcp_server, mcp_app = create_mcp_server()
    app = FastAPI(
        title="AI Service",
        lifespan=partial(application_lifespan, mcp_server=mcp_server),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(
        create_session_router(get_agent_registry),
        responses={
            405: {"model": HttpErrorResponse},
            500: {"model": HttpErrorResponse},
        },
    )
    app.include_router(embedding_router)
    app.include_router(transcription_router)
    register_error_handlers(app)
    app.mount("/mcp", mcp_app)
    return app


app = create_app()
