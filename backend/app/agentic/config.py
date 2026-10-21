"""Execution defaults for the Pydantic AI engine."""

from datetime import timedelta
from typing import Final


MAX_MODEL_REQUESTS: Final[int] = 40
MAX_TOOL_CALLS: Final[int] = 32
MAX_NATIVE_TOOL_CALLS_PER_RESPONSE: Final[int] = 16
MAX_OUTPUT_TOKENS: Final[int] = 16_384
MAX_CONTEXT_LENGTH: Final[int] = 64_000
MAX_PROMPT_LENGTH: Final[int] = 16_000
MAX_ARTIFACTS: Final[int] = 100
DEFAULT_SESSION_LIFETIME: Final[timedelta] = timedelta(minutes=90)
MAX_OBSERVERS_PER_SESSION: Final[int] = 8
MAX_PENDING_OBSERVATION_UPDATES: Final[int] = 128

MODEL_NETWORK_TIMEOUT_SECONDS: Final[float] = 120.0
MODEL_REQUEST_TIMEOUT_SECONDS: Final[float] = 120.0
TOOL_TIMEOUT_SECONDS: Final[float] = 60.0
MCP_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
MCP_READ_TIMEOUT_SECONDS: Final[float] = 60.0

MODEL_MAX_RETRIES: Final[int] = 0
VALIDATION_MAX_RETRIES: Final[int] = 0
