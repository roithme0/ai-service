import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.models import HttpErrorResponse, RequestValidationErrorResponse
from app.capabilities.embeddings.models import (
    EmbeddingErrorResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.capabilities.embeddings.service import EmbeddingService, EmbeddingUnavailable

logger = logging.getLogger(__name__)
router = APIRouter()


def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.embedding_service


@router.post(
    "/api/v1/embeddings",
    response_model=EmbeddingResponse,
    responses={
        422: {"model": RequestValidationErrorResponse},
        502: {"model": EmbeddingErrorResponse},
        503: {"model": EmbeddingErrorResponse},
        500: {"model": HttpErrorResponse},
    },
)
async def embed(
    body: EmbeddingRequest,
    service: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> EmbeddingResponse | JSONResponse:
    try:
        return await service.embed(body.input)
    except EmbeddingUnavailable:
        error = EmbeddingErrorResponse(
            kind="embedding_unavailable", detail="Embedding provider is not configured"
        )
        return JSONResponse(status_code=503, content=error.model_dump())
    except Exception as failure:
        logger.warning("Embedding generation failed (%s)", type(failure).__name__)
        error = EmbeddingErrorResponse(
            kind="embedding_failed", detail="Embedding generation failed"
        )
        return JSONResponse(status_code=502, content=error.model_dump())
