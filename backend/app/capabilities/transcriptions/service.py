"""OpenAI transcription resource."""

import asyncio

import openai
from httpx2 import AsyncClient
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.capabilities.transcriptions.config import TranscriptionSettings
from app.core.config import ProviderSettings


class TranscriptionUnavailable(Exception):
    pass


class InvalidAudio(Exception):
    pass


class TranscriptionFailed(Exception):
    pass


class TranscriptionService:
    def __init__(
        self, api_key: str | None, model: str, *, http_client: AsyncClient | None = None
    ) -> None:
        self.model = model.strip()
        self.client: AsyncOpenAI | None = None
        if api_key and self.model:
            self.client = AsyncOpenAI(
                api_key=api_key,
                http_client=http_client or DefaultAsyncHttpxClient(),
                max_retries=0,
                timeout=120.0,
            )

    @classmethod
    def from_settings(
        cls, provider: ProviderSettings, settings: TranscriptionSettings
    ) -> "TranscriptionService":
        key = provider.openai_api_key
        return cls(
            key.get_secret_value() if key else None, settings.transcription_openai_model
        )

    async def transcribe(self, audio: bytes, media_type: str, suffix: str) -> str:
        if self.client is None:
            raise TranscriptionUnavailable()
        try:
            async with asyncio.timeout(120.0):
                response = (
                    await self.client.audio.transcriptions.with_raw_response.create(
                        file=(f"recording{suffix}", audio, media_type),
                        model=self.model,
                        response_format="json",
                    )
                )
                try:
                    body = response.http_response.json()
                except ValueError as exc:
                    raise TranscriptionFailed() from exc
        except openai.RateLimitError as exc:
            raise TranscriptionUnavailable() from exc
        except openai.APIStatusError as exc:
            if exc.code in {"invalid_audio", "invalid_audio_format"}:
                raise InvalidAudio() from exc
            if exc.status_code == 503:
                raise TranscriptionUnavailable() from exc
            raise TranscriptionFailed() from exc
        except openai.APITimeoutError as exc:
            raise TimeoutError() from exc
        except openai.APIError as exc:
            raise TranscriptionFailed() from exc
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise TranscriptionFailed()
        return body["text"]

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
