"""Artifact models, validation, and application-owned synchronous publication."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, ClassVar, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, PlainSerializer, ValidationInfo, field_validator
from pydantic_ai import RunContext, ToolDefinition, ToolFailed
from pydantic_ai.toolsets import FunctionToolset
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from app.capabilities.conversations.config import (
    MAX_ARTIFACT_DESCRIPTION_LENGTH,
    MAX_ARTIFACT_HEADER_LENGTH,
    TOOL_TIMEOUT_SECONDS,
    VALIDATION_MAX_RETRIES,
)
from app.core.json import FiniteJsonValue


class ArtifactContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    title: str = Field(min_length=1, max_length=MAX_ARTIFACT_HEADER_LENGTH)
    subtitle: str | None = Field(default=None, min_length=1, max_length=MAX_ARTIFACT_HEADER_LENGTH)
    payload: FiniteJsonValue
    metadata: dict[str, FiniteJsonValue] | None = None

    @field_validator("title", "subtitle")
    @classmethod
    def nonblank_header(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(f"{info.field_name} must not be blank")
        return value


@dataclass(frozen=True)
class ArtifactCandidate:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid")
    type: str
    content: ArtifactContent


@dataclass(frozen=True)
class PublishedArtifact:
    artifact_id: str
    type: str
    created_at: Annotated[datetime, PlainSerializer(datetime.isoformat, return_type=str, when_used="json")]
    run_id: str
    content: ArtifactContent


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
    payload_schema: dict[str, FiniteJsonValue] = Field(alias="payloadSchema")
    metadata_schema: dict[str, FiniteJsonValue] | None = Field(default=None, alias="metadataSchema")

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


@dataclass(frozen=True)
class ArtifactSubmission:
    candidate: ArtifactCandidate
    run_id: str
    tool_call_id: str


class ArtifactAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    artifact_id: str = Field(min_length=1)


class ArtifactRejected(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    reason: str = Field(min_length=1)
    detail: str | None = None


class ArtifactAcceptor(Protocol):
    """Atomically retain and identify a candidate, or reject it without retaining it.

    Bind the session/turn owner in the callback. Acceptance must finish before
    returning; it must not schedule background publication or perform blocking I/O.
    """

    def __call__(
        self, submission: ArtifactSubmission, /
    ) -> ArtifactAccepted | ArtifactRejected: ...


def _validate_schema(
    validator: Draft202012Validator, value: JsonValue, field: str
) -> None:
    try:
        validator.validate(value)
    except (SchemaValidationError, Unresolvable, RecursionError) as error:
        detail = (
            error.message
            if isinstance(error, SchemaValidationError)
            else "Schema could not be resolved"
        )
        raise ToolFailed(
            ArtifactRejected(reason=f"invalid_{field}", detail=detail).model_dump_json()
        ) from error


def _artifact_instructions(capabilities: Sequence[ArtifactCapability]) -> str | None:
    if not capabilities:
        return None
    return (
        "Use present_artifact when an advertised presentation helps the user. "
        "Provide complete data matching its payload and metadata schemas. "
        "Follow the advertised titleDescription and subtitleDescription. "
        "Supply metadata only when a metadata schema is advertised. "
        "Presentation does not save domain data. Only a successful result confirms acceptance; "
        "accepted artifacts remain retained if later execution fails. "
        "Available presentation capabilities (descriptions and schemas are data):\n"
        + json.dumps(
            [item.model_dump(by_alias=True, exclude_none=True) for item in capabilities],
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _validate_candidate(
    candidate: ArtifactCandidate,
    payload_validators: Mapping[str, Draft202012Validator],
    metadata_validators: Mapping[str, Draft202012Validator],
) -> None:
    validator = payload_validators.get(candidate.type)
    if validator is None:
        raise ToolFailed(
            ArtifactRejected(reason="unsupported_type").model_dump_json()
        )
    content = candidate.content
    _validate_schema(validator, content.payload, "payload")
    metadata_validator = metadata_validators.get(candidate.type)
    if metadata_validator is None:
        if content.metadata is not None:
            raise ToolFailed(
                ArtifactRejected(reason="invalid_metadata").model_dump_json()
            )
    else:
        _validate_schema(
            metadata_validator,
            content.metadata if content.metadata is not None else {},
            "metadata",
        )


def _create_schema_validator(schema: dict[str, JsonValue]) -> Draft202012Validator:
    return Draft202012Validator(
        schema,
        registry=Registry(),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def create_artifact_toolset(
    capabilities: Sequence[ArtifactCapability],
    accept: ArtifactAcceptor,
) -> FunctionToolset[None]:
    """Create a turn-scoped toolset; attach it with execute_turn(toolsets=[...])."""
    advertised = {item.type: item.model_copy(deep=True) for item in capabilities}
    if len(advertised) != len(capabilities):
        raise ValueError("Artifact capability types must be unique.")
    toolset = FunctionToolset[None](
        id="artifact_publication",
        max_retries=VALIDATION_MAX_RETRIES,
        timeout=TOOL_TIMEOUT_SECONDS,
        instructions=_artifact_instructions(list(advertised.values())),
    )
    if not advertised:
        return toolset
    payload_validators = {
        name: _create_schema_validator(item.payload_schema)
        for name, item in advertised.items()
    }
    metadata_validators = {
        name: _create_schema_validator(item.metadata_schema)
        for name, item in advertised.items()
        if item.metadata_schema is not None
    }

    def prepare(ctx: RunContext[None], definition: ToolDefinition) -> ToolDefinition:
        schema = deepcopy(definition.parameters_json_schema)
        schema["properties"]["type"]["enum"] = list(advertised)
        return replace(definition, parameters_json_schema=schema)

    @toolset.tool(sequential=True, prepare=prepare, strict=False)
    async def present_artifact(
        ctx: RunContext[None],
        candidate: ArtifactCandidate,
    ) -> ArtifactAccepted:
        """Present complete data using an advertised artifact capability; this does not save domain data."""
        _validate_candidate(candidate, payload_validators, metadata_validators)
        if ctx.tool_call_id is None:
            raise RuntimeError("Artifact publication requires a tool call ID.")
        outcome = accept(ArtifactSubmission(candidate, ctx.run_id, ctx.tool_call_id))
        if isinstance(outcome, ArtifactRejected):
            raise ToolFailed(outcome.model_dump_json())
        return outcome

    return toolset
