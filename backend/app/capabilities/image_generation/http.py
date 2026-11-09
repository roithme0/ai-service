"""HTTP endpoints for image generation."""

import asyncio
import logging
from contextlib import aclosing
from collections.abc import AsyncGenerator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.types import Receive, Scope, Send

from app.capabilities.image_generation.models import GenerationRequest, Snapshot
from app.capabilities.image_generation.service import (
    Conflict,
    ImageGenerationService,
    Record,
    Unavailable,
)
from app.core.http import require_application_user
from app.core.identity import ApplicationIdentity
from app.core.sse import EventStreamResponse, frame, with_heartbeats
from app.core.models import (
    ErrorEnvelope,
    HttpErrorResponse,
    RequestValidationErrorResponse,
)

router = APIRouter()
CACHE = {"Cache-Control": "private, no-store"}
ImageError = ErrorEnvelope[
    Literal[
        "image_generation_unavailable",
        "image_generation_idempotency_conflict",
        "image_generation_not_completed",
    ]
]
RESPONSES = {
    404: {"model": HttpErrorResponse},
    422: {"model": RequestValidationErrorResponse},
    500: {"model": HttpErrorResponse},
}


def service(request: Request) -> ImageGenerationService:
    return request.app.state.image_generation_service


def key_header(
    request: Request, key: Annotated[UUID, Header(alias="Idempotency-Key")]
) -> UUID:
    if len(request.headers.getlist("Idempotency-Key")) != 1:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("header", "Idempotency-Key"),
                    "msg": "Exactly one key is required.",
                    "input": None,
                }
            ]
        )
    return key


def error(status: int, kind: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"kind": kind, "detail": detail}, headers=CACHE
    )


@router.post(
    "/api/v1/image-generations",
    response_model=Snapshot,
    status_code=202,
    responses={
        200: {
            "model": Snapshot,
            "headers": {"Location": {"schema": {"type": "string"}}},
        },
        202: {"headers": {"Location": {"schema": {"type": "string"}}}},
        409: {"model": ImageError},
        503: {"model": ImageError},
        **RESPONSES,
    },
)
async def submit(
    body: GenerationRequest,
    response: Response,
    owner: Annotated[ApplicationIdentity, Depends(require_application_user)],
    key: Annotated[UUID, Depends(key_header)],
    generation: Annotated[ImageGenerationService, Depends(service)],
) -> Snapshot | JSONResponse:
    try:
        snapshot, created = generation.submit(owner, key, body.instructions)
    except Conflict:
        return error(
            409,
            "image_generation_idempotency_conflict",
            "Idempotency key conflicts with an existing request",
        )
    except Unavailable:
        return error(
            503, "image_generation_unavailable", "Image generation is unavailable"
        )
    response.status_code = 202 if created else 200
    response.headers.update(CACHE)
    response.headers["Location"] = f"/api/v1/image-generations/{snapshot.generation_id}"
    return snapshot


@router.get(
    "/api/v1/image-generations/{generation_id}",
    response_model=Snapshot,
    responses=RESPONSES,
)
async def status(
    generation_id: UUID,
    response: Response,
    owner: Annotated[ApplicationIdentity, Depends(require_application_user)],
    generation: Annotated[ImageGenerationService, Depends(service)],
) -> Snapshot | JSONResponse:
    record = generation.get(owner, generation_id)
    if not record:
        return error(404, "not_found", "Not Found")
    response.headers.update(CACHE)
    return record.snapshot


@router.get(
    "/api/v1/image-generations/{generation_id}/content",
    response_class=FileResponse,
    responses={
        200: {
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}}
            },
            "headers": {
                "Content-Length": {"schema": {"type": "integer"}},
                "Content-Disposition": {"schema": {"type": "string"}},
            },
        },
        409: {"model": ImageError},
        **RESPONSES,
    },
)
async def content(
    generation_id: UUID,
    owner: Annotated[ApplicationIdentity, Depends(require_application_user)],
    generation: Annotated[ImageGenerationService, Depends(service)],
) -> Response:
    record = generation.get(owner, generation_id)
    if not record:
        return error(404, "not_found", "Not Found")
    if record.snapshot.status != "completed" or not record.path:
        return error(
            409, "image_generation_not_completed", "Image generation is not completed"
        )
    try:
        data = await asyncio.to_thread(record.path.read_bytes)
    except OSError:
        return error(500, "internal_error", "Internal Server Error")
    return Response(
        data,
        media_type="image/png",
        headers={
            **CACHE,
            "Content-Disposition": f'attachment; filename="{generation_id}.png"',
        },
    )


class SnapshotEvent(BaseModel):
    kind: Literal["snapshot"]
    snapshot: Snapshot


class ObservationErrorEvent(BaseModel):
    kind: Literal["error"]
    reason: Literal["internal_error"]


type ImageEvent = Annotated[
    SnapshotEvent | ObservationErrorEvent, Field(discriminator="kind")
]


async def _updates(
    queue: asyncio.Queue[Snapshot | None],
) -> AsyncGenerator[Snapshot, None]:
    while (snapshot := await queue.get()) is not None:
        yield snapshot
        if snapshot.status != "running":
            return


async def _events(
    first: Snapshot, updates: AsyncGenerator[Snapshot, None]
) -> AsyncGenerator[str, None]:
    try:
        yield frame(SnapshotEvent(kind="snapshot", snapshot=first))
        if first.status != "running":
            return
        async with aclosing(with_heartbeats(updates)) as stream:
            async for snapshot in stream:
                if snapshot is None:
                    yield ": heartbeat\n\n"
                else:
                    yield frame(SnapshotEvent(kind="snapshot", snapshot=snapshot))
                    if snapshot.status != "running":
                        return
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Image observation failed (%s)", type(exc).__name__
        )
        yield frame(ObservationErrorEvent(kind="error", reason="internal_error"))


class ImageEventResponse(EventStreamResponse):
    def __init__(
        self,
        generation: ImageGenerationService,
        record: Record,
        first: Snapshot,
        queue: asyncio.Queue[Snapshot | None],
    ) -> None:
        self.generation = generation
        self.record = record
        self.queue = queue
        updates = _updates(queue)
        super().__init__(_events(first, updates), updates, "private, no-store")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.generation.unsubscribe(self.record, self.queue)


@router.get(
    "/api/v1/image-generations/{generation_id}/events",
    status_code=200,
    response_class=EventStreamResponse,
    response_model=ImageEvent,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"$ref": "#/components/schemas/ImageEvent"}
                }
            }
        },
        **RESPONSES,
    },
)
async def events(
    generation_id: UUID,
    owner: Annotated[ApplicationIdentity, Depends(require_application_user)],
    generation: Annotated[ImageGenerationService, Depends(service)],
) -> Response:
    subscription = generation.subscribe(owner, generation_id)
    if subscription is None:
        return error(404, "not_found", "Not Found")
    first, queue = subscription
    record = generation.get(owner, generation_id)
    assert record is not None
    return ImageEventResponse(generation, record, first, queue)
