"""Conversation configuration and execution defaults."""

from datetime import timedelta
from functools import lru_cache
from typing import Final

from openai.types.shared import ReasoningEffort
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ENV_FILE


class KochwikiConversationSettings(BaseSettings):
    kochwiki_openai_model: str | None = None
    kochwiki_openai_reasoning_effort: ReasoningEffort = None
    kochwiki_mcp_url: str | None = None

    model_config = SettingsConfigDict(
        env_file=BACKEND_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "kochwiki_openai_model",
        "kochwiki_openai_reasoning_effort",
        "kochwiki_mcp_url",
        mode="before",
    )
    @classmethod
    def empty_strings_are_unset(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


@lru_cache(maxsize=1)
def get_kochwiki_conversation_settings() -> KochwikiConversationSettings:
    return KochwikiConversationSettings()


MAX_MODEL_REQUESTS_PER_TURN: Final[int] = 40
MAX_TOOL_CALLS_PER_TURN: Final[int] = 32

MAX_MODEL_REQUESTS_PER_CONVERSATION: Final[int] = 50
MAX_TOOL_CALLS_PER_CONVERSATION: Final[int] = 40

MAX_NATIVE_TOOL_CALLS_PER_RESPONSE: Final[int] = 16
MAX_OUTPUT_TOKENS: Final[int] = 16_384

MAX_INITIAL_CONTEXT_CHARACTERS: Final[int] = 64_000
MAX_PROMPT_CHARACTERS: Final[int] = 16_000

MAX_ARTIFACTS_PER_SESSION: Final[int] = 100
MAX_ARTIFACT_HEADER_LENGTH: Final[int] = 200
MAX_ARTIFACT_DESCRIPTION_LENGTH: Final[int] = 2_000

DEFAULT_SESSION_LIFETIME: Final[timedelta] = timedelta(minutes=90)
MAX_OBSERVERS_PER_SESSION: Final[int] = 8
MAX_PENDING_OBSERVATION_UPDATES: Final[int] = 128

MODEL_NETWORK_TIMEOUT_SECONDS: Final[float] = 120.0
MODEL_REQUEST_TIMEOUT_SECONDS: Final[float] = 120.0
TOOL_TIMEOUT_SECONDS: Final[float] = 60.0
MCP_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
MCP_READ_TIMEOUT_SECONDS: Final[float] = 60.0

MODEL_REQUEST_MAX_RETRIES: Final[int] = 0
VALIDATION_MAX_RETRIES: Final[int] = 0
