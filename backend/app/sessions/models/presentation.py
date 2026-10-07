"""Advertised presentation capabilities and retained artifact payloads."""

from __future__ import annotations

import json
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Resource
from referencing.jsonschema import DRAFT202012
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class ArtifactCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    type: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    description: str = Field(min_length=1, max_length=2000)
    title_description: str | None = Field(default=None, alias="titleDescription", min_length=1, max_length=2000)
    subtitle_description: str | None = Field(default=None, alias="subtitleDescription", min_length=1, max_length=2000)
    payload_schema: dict[str, JsonValue] = Field(alias="payloadSchema")
    metadata_schema: dict[str, JsonValue] | None = Field(default=None, alias="metadataSchema")

    @field_validator("title_description", "subtitle_description")
    @classmethod
    def nonblank_header_description(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("header descriptions must not be blank")
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
            raise ValueError("must be a valid, self-contained JSON Schema (draft 2020-12)") from error
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


class PresentationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    title: str = Field(min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, min_length=1, max_length=200)
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
