"""Transcription resource lifetime."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.capabilities.transcriptions.config import TranscriptionSettings
from app.capabilities.transcriptions.service import TranscriptionService
from app.core.config import ProviderSettings


@asynccontextmanager
async def transcription_service(
    settings: ProviderSettings,
) -> AsyncIterator[TranscriptionService]:
    service = TranscriptionService.from_settings(settings, TranscriptionSettings())
    try:
        yield service
    finally:
        await service.close()
