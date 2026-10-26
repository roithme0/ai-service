from httpx2 import AsyncClient
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic_ai import Embedder
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.core.config import ProviderSettings
from app.capabilities.embeddings.config import MODEL
from app.capabilities.embeddings.models import EmbeddingResponse


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingService:
    def __init__(
        self, api_key: str | None, *, http_client: AsyncClient | None = None
    ) -> None:
        self.client: AsyncOpenAI | None = None
        self.embedder: Embedder | None = None
        if api_key is not None:
            http_client = http_client or DefaultAsyncHttpxClient()
            self.client = AsyncOpenAI(
                api_key=api_key, http_client=http_client, max_retries=0, timeout=30.0
            )
            self.embedder = Embedder(
                OpenAIEmbeddingModel(
                    MODEL, provider=OpenAIProvider(openai_client=self.client)
                ),
                settings={"extra_body": {"encoding_format": "float"}},
                instrument=False,
            )

    @classmethod
    def from_settings(cls, settings: ProviderSettings) -> "EmbeddingService":
        key = settings.openai_api_key
        return cls(key.get_secret_value() if key else None)

    async def embed(self, text: str) -> EmbeddingResponse:
        if self.embedder is None:
            raise EmbeddingUnavailable("Embedding provider is not configured")
        response = await self.embedder.embed_query(text)
        if response.model_name != MODEL or len(response.embeddings) != 1:
            raise ValueError("Embedding response differs from request")
        return EmbeddingResponse(vector=list(response.embeddings[0]))

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
