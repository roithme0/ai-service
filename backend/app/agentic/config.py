"""Execution defaults for the Pydantic AI engine."""

from typing import Final


MAX_MODEL_REQUESTS: Final[int] = 40
MAX_TOOL_CALLS: Final[int] = 32
MAX_OUTPUT_TOKENS: Final[int] = 16_384

MODEL_NETWORK_TIMEOUT_SECONDS: Final[float] = 120.0
MODEL_REQUEST_TIMEOUT_SECONDS: Final[float] = 120.0
TOOL_TIMEOUT_SECONDS: Final[float] = 60.0
MCP_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
MCP_READ_TIMEOUT_SECONDS: Final[float] = 60.0

MODEL_MAX_RETRIES: Final[int] = 0
VALIDATION_MAX_RETRIES: Final[int] = 0
