from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import ProviderSettings
from app.capabilities.embeddings.service import EmbeddingService


@asynccontextmanager
async def embedding_service(
    provider_settings: ProviderSettings,
) -> AsyncIterator[EmbeddingService]:
    service = EmbeddingService.from_settings(provider_settings)
    try:
        yield service
    finally:
        await service.close()
