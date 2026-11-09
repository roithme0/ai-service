"""Public image generation contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerationRequest(StrictModel):
    instructions: str = Field(min_length=1, max_length=32000, strict=True)

    @field_validator("instructions")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Instructions must not be blank")
        return value


class SnapshotBase(StrictModel):
    generation_id: UUID
    created_at: datetime
    completed_at: datetime | None
    configured_model: str
    provider_model: str | None
    estimated_cost_usd: Decimal | None


class RunningSnapshot(SnapshotBase):
    status: Literal["running"]
    completed_at: None


class Content(StrictModel):
    url: str
    media_type: Literal["image/png"]
    size_bytes: int = Field(gt=0)


class CompletedSnapshot(SnapshotBase):
    status: Literal["completed"]
    completed_at: datetime
    content: Content


class Failure(StrictModel):
    kind: Literal[
        "image_generation_timeout",
        "image_generation_rejected",
        "image_generation_provider_failed",
        "image_generation_invalid_output",
        "image_generation_storage_failed",
        "image_generation_failed",
    ]
    detail: str


class FailedSnapshot(SnapshotBase):
    status: Literal["failed"]
    completed_at: datetime
    error: Failure


type Snapshot = Annotated[
    RunningSnapshot | CompletedSnapshot | FailedSnapshot, Field(discriminator="status")
]
