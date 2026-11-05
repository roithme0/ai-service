"""Typed transcription contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.models import ErrorEnvelope


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


class TranscriptionErrorResponse(
    ErrorEnvelope[
        Literal[
            "audio_too_large",
            "unsupported_audio",
            "invalid_audio",
            "transcription_unavailable",
            "transcription_timeout",
            "transcription_failed",
        ]
    ]
):
    pass
