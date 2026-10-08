"""Artifact capabilities, payloads, candidates, and retained envelopes."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from app.sessions.config import MAX_ARTIFACT_DESCRIPTION_LENGTH, MAX_ARTIFACT_HEADER_LENGTH

ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class ArtifactCandidate(Generic[ArtifactT]):
    type: str
    payload: ArtifactT


@dataclass(frozen=True)
class ArtifactEnvelope(Generic[ArtifactT]):
    artifact_id: str
    type: str
    created_at: datetime
    turn_id: str
    payload: ArtifactT


@dataclass(frozen=True)
class PublishedArtifact(ArtifactEnvelope[ArtifactT]):
    order: int


@dataclass(frozen=True)
class ArtifactToolOutput:
    kind: str


class ArtifactCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    type: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    description: str = Field(min_length=1, max_length=MAX_ARTIFACT_DESCRIPTION_LENGTH)
    title_description: str | None = Field(
        default=None, alias="titleDescription", min_length=1,
        max_length=MAX_ARTIFACT_DESCRIPTION_LENGTH,
    )
    subtitle_description: str | None = Field(
        default=None, alias="subtitleDescription", min_length=1,
        max_length=MAX_ARTIFACT_DESCRIPTION_LENGTH,
    )
    payload_schema: dict[str, JsonValue] = Field(alias="payloadSchema")
    metadata_schema: dict[str, JsonValue] | None = Field(default=None, alias="metadataSchema")

    @field_validator("description", "title_description", "subtitle_description")
    @classmethod
    def nonblank_description(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("descriptions must not be blank")
        return value

    @field_validator("payload_schema", "metadata_schema")
    @classmethod
    def validate_schema(cls, schema: dict[str, JsonValue] | None) -> dict[str, JsonValue] | None:
        if schema is None:
            return None
        try:
            json.dumps(schema, allow_nan=False)
            Draft202012Validator.check_schema(schema)
            _check_schema_references(Resource.from_contents(schema, default_specification=DRAFT202012))
        except (SchemaError, ValueError, RecursionError) as error:
            raise ValueError(
                "must be a valid JSON Schema (draft 2020-12) without external references"
            ) from error
        return deepcopy(schema)


def _check_schema_references(resource: Resource[JsonValue]) -> None:
    schema = resource.contents
    if isinstance(schema, dict):
        for key in ("$ref", "$dynamicRef"):
            reference = schema.get(key)
            if isinstance(reference, str) and not reference.startswith("#"):
                raise ValueError("external schema references are not supported")
        if "$schema" in schema and schema["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("only draft 2020-12 is supported")
    for child in resource.subresources():
        _check_schema_references(child)


class ArtifactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    title: str = Field(min_length=1, max_length=MAX_ARTIFACT_HEADER_LENGTH)
    subtitle: str | None = Field(default=None, min_length=1, max_length=MAX_ARTIFACT_HEADER_LENGTH)
    payload: JsonValue
    metadata: dict[str, JsonValue] | None = None

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("subtitle")
    @classmethod
    def nonblank_subtitle(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("subtitle must not be blank")
        return value
