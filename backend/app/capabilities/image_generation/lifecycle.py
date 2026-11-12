"""Image generation lifespan."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.capabilities.image_generation.config import ImageGenerationSettings
from app.capabilities.image_generation.service import ImageGenerationService
from app.capabilities.image_generation.storage import initialize
from app.core.config import ProviderSettings


@asynccontextmanager
async def image_generation_service(
    settings: ProviderSettings,
) -> AsyncIterator[ImageGenerationService]:
    config = ImageGenerationSettings()
    run = (
        await asyncio.to_thread(initialize, Path(config.image_generation_storage_root))
        if config.image_generation_storage_root
        else None
    )
    service = ImageGenerationService.create(settings, config, run)
    try:
        yield service
    finally:
        await service.close()
