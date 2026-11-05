"""Standalone raw-audio transcription endpoint."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from app.capabilities.transcriptions.models import (
    TranscriptionErrorResponse,
    TranscriptionResponse,
)
from app.capabilities.transcriptions.service import (
    InvalidAudio,
    TranscriptionFailed,
    TranscriptionService,
    TranscriptionUnavailable,
)
from app.core.models import HttpErrorResponse

MAX_AUDIO_BYTES = 25_000_000
MEDIA_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mpga": ".mpga",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}
router = APIRouter()


def get_transcription_service(request: Request) -> TranscriptionService:
    return request.app.state.transcription_service


def error(status: int, kind: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"kind": kind, "detail": detail})


async def wait_for_disconnect(request: Request) -> None:
    while True:
        message = await request.receive()
        if message["type"] == "http.disconnect":
            return


@router.post(
    "/api/v1/transcriptions",
    response_model=TranscriptionResponse,
    responses={
        413: {"model": TranscriptionErrorResponse},
        415: {"model": TranscriptionErrorResponse},
        422: {"model": TranscriptionErrorResponse},
        502: {"model": TranscriptionErrorResponse},
        503: {"model": TranscriptionErrorResponse},
        504: {"model": TranscriptionErrorResponse},
        500: {"model": HttpErrorResponse},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in MEDIA_SUFFIXES
            },
        }
    },
)
async def transcribe(
    request: Request,
    service: Annotated[TranscriptionService, Depends(get_transcription_service)],
) -> TranscriptionResponse | JSONResponse:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    suffix = MEDIA_SUFFIXES.get(media_type)
    if suffix is None:
        return error(415, "unsupported_audio", "Unsupported audio content type")
    audio = bytearray()
    try:
        async for chunk in request.stream():
            if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                return error(413, "audio_too_large", "Audio exceeds the size limit")
            audio.extend(chunk)
        if not audio:
            return error(422, "invalid_audio", "Audio is empty or invalid")
        operation = asyncio.create_task(
            service.transcribe(bytes(audio), content_type, suffix)
        )
        disconnect = asyncio.create_task(wait_for_disconnect(request))
        try:
            done, _ = await asyncio.wait(
                {operation, disconnect}, return_when=asyncio.FIRST_COMPLETED
            )
            if disconnect in done:
                raise ClientDisconnect()
            text = await operation
            return TranscriptionResponse(text=text)
        finally:
            operation.cancel()
            disconnect.cancel()
            await asyncio.gather(operation, disconnect, return_exceptions=True)
    except InvalidAudio:
        return error(422, "invalid_audio", "Audio is empty or invalid")
    except TranscriptionUnavailable:
        return error(503, "transcription_unavailable", "Transcription is unavailable")
    except TimeoutError:
        return error(504, "transcription_timeout", "Transcription timed out")
    except TranscriptionFailed:
        return error(502, "transcription_failed", "Transcription failed")
    finally:
        audio.clear()
