from openai import AsyncOpenAI

from app.core.config import ProviderSettings
from app.capabilities.embeddings.config import MODEL
from app.capabilities.embeddings.models import EmbeddingResponse


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingService:
    def __init__(self, client: AsyncOpenAI | None) -> None:
        self.client = client

    @classmethod
    def from_settings(cls, settings: ProviderSettings) -> "EmbeddingService":
        key = settings.openai_api_key
        client = (
            AsyncOpenAI(api_key=key.get_secret_value(), max_retries=0, timeout=30.0)
            if key
            else None
        )
        return cls(client)

    async def embed(self, text: str) -> EmbeddingResponse:
        if self.client is None:
            raise EmbeddingUnavailable("Embedding provider is not configured")
        response = await self.client.embeddings.create(
            input=text, model=MODEL, encoding_format="float"
        )
        if (
            response.model != MODEL
            or len(response.data) != 1
            or response.data[0].index != 0
        ):
            raise ValueError("Embedding response differs from request")
        return EmbeddingResponse(vector=response.data[0].embedding)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
