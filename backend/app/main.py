from collections.abc import Mapping

from fastapi import FastAPI, Request

from app.capabilities.conversations.http import create_session_router
from app.capabilities.conversations.runner import AgentTurnRunner
from app.capabilities.embeddings.http import router as embedding_router
from app.core.http import register_error_handlers
from app.core.models import HttpErrorResponse
from app.lifespan import application_lifespan


def get_agent_registry(request: Request) -> Mapping[str, AgentTurnRunner | None]:
    return request.app.state.agent_runners


app = FastAPI(
    title="AI Service",
    lifespan=application_lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(create_session_router(get_agent_registry), responses={
    405: {"model": HttpErrorResponse},
    500: {"model": HttpErrorResponse},
})
app.include_router(embedding_router)
register_error_handlers(app)
