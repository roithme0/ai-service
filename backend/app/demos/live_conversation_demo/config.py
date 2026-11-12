from functools import lru_cache

from openai.types.shared import ReasoningEffort
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ENV_FILE


class LiveConversationDemoSettings(BaseSettings):
    live_demo_openai_model: str | None = None
    live_demo_openai_reasoning_effort: ReasoningEffort = None

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator(
        "live_demo_openai_model", "live_demo_openai_reasoning_effort", mode="before"
    )
    @classmethod
    def empty_strings_are_unset(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


@lru_cache(maxsize=1)
def get_live_conversation_demo_settings() -> LiveConversationDemoSettings:
    return LiveConversationDemoSettings()
