"""Typed application configuration loaded from the process environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    openai_api_key: SecretStr | None = None
    recipe_improvement_openai_model: str | None = None
    kochwiki_base_url: str | None = None

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "openai_api_key", "recipe_improvement_openai_model", "kochwiki_base_url", mode="before"
    )
    @classmethod
    def empty_strings_are_unset(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
