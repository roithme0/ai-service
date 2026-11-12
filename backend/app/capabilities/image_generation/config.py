"""Image generation configuration."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.config import BACKEND_ENV_FILE


class ImageGenerationSettings(BaseSettings):
    image_generation_openai_model: str | None = None
    image_generation_storage_root: str | None = None
    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator(
        "image_generation_openai_model", "image_generation_storage_root", mode="before"
    )
    @classmethod
    def blank_is_absent(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value
