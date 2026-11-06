"""Transcription capability configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ENV_FILE


class TranscriptionSettings(BaseSettings):
    transcription_openai_model: str = "gpt-transcribe"

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )
