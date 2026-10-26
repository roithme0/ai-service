from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.capabilities.embeddings.config import DIMENSIONS, MODEL, PROFILE
from app.core.models import ErrorEnvelope


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    profile: Literal["semantic-text-v1"]
    input: str = Field(min_length=1)

    @field_validator("input")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Input must not be blank")
        return value


class EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    profile: Literal["semantic-text-v1"] = PROFILE
    model: Literal["text-embedding-3-large"] = MODEL
    dimensions: Literal[3072] = DIMENSIONS
    vector: list[float] = Field(min_length=DIMENSIONS, max_length=DIMENSIONS)

    @field_validator("vector")
    @classmethod
    def require_nonzero(cls, value: list[float]) -> list[float]:
        if not any(value):
            raise ValueError("Embedding must be nonzero")
        return value


class EmbeddingErrorResponse(
    ErrorEnvelope[Literal["embedding_unavailable", "embedding_failed"]]
):
    pass
