"""Caller-advertised presentation contracts and the local artifact tool."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Literal, TypeVar

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from referencing.exceptions import Unresolvable
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from app.sessions.conversation import ConversationSessionStore, ConversationStageAccepted, StagedArtifact
from app.sessions.tools import LocalToolSource, RegisteredTool, ToolExecution, ToolInvocation

ContextT = TypeVar("ContextT")


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


class PresentationRequest(PresentationPayload):
    type: str


def _schema_rejection(
    validator: Draft202012Validator, value: JsonValue, field: Literal["payload", "metadata"],
) -> str | None:
    try:
        issue = next(validator.iter_errors(value), None)
    except (Unresolvable, RecursionError):
        return json.dumps({"kind": "rejected", "reason": f"invalid_{field}",
                           "detail": f"{field.capitalize()} schema could not be resolved"})
    if issue is not None:
        return json.dumps({"kind": "rejected", "reason": f"invalid_{field}",
                           "location": list(issue.path), "detail": issue.message})
    return None


def presentation_tool_source(
    capabilities: tuple[ArtifactCapability, ...],
    store: ConversationSessionStore[ContextT, PresentationPayload],
    session_id: str,
    turn_id: str,
) -> LocalToolSource[StagedArtifact[PresentationPayload]]:
    validators = {item.type: Draft202012Validator(item.payload_schema, registry=Registry()) for item in capabilities}
    metadata_validators = {item.type: Draft202012Validator(item.metadata_schema, registry=Registry(),
                           format_checker=Draft202012Validator.FORMAT_CHECKER)
                           for item in capabilities if item.metadata_schema is not None}

    def execute(call: ToolInvocation) -> ToolExecution[StagedArtifact[PresentationPayload]]:
        try:
            request = PresentationRequest.model_validate_json(call.arguments)
            json.dumps(request.payload, allow_nan=False)
            json.dumps(request.metadata, allow_nan=False)
        except (ValidationError, ValueError, RecursionError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}))
        validator = validators.get(request.type)
        if validator is None:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "unsupported_type"}))
        rejection = _schema_rejection(validator, request.payload, "payload")
        if rejection is not None:
            return ToolExecution(rejection)
        metadata_validator = metadata_validators.get(request.type)
        if metadata_validator is None:
            if request.metadata is not None:
                return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_metadata",
                                                 "detail": "This capability does not advertise metadata"}))
        else:
            rejection = _schema_rejection(metadata_validator, request.metadata or {}, "metadata")
            if rejection is not None:
                return ToolExecution(rejection)
        staged = store.stage_artifact(
            session_id, turn_id, request.type,
            PresentationPayload(title=request.title, subtitle=request.subtitle, payload=request.payload,
                                metadata=request.metadata),
        )
        if not isinstance(staged, ConversationStageAccepted):
            return ToolExecution(json.dumps({"kind": staged.kind}))
        return ToolExecution(json.dumps({"kind": "presented", "artifact_id": staged.artifact.artifact_id}), staged.artifact)

    return LocalToolSource((RegisteredTool("present_artifact", {
        "type": "function", "name": "present_artifact", "strict": False,
        "description": "Present complete data to the user using an advertised artifact capability. This has no domain save effect.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": [item.type for item in capabilities]},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "subtitle": {"type": ["string", "null"], "minLength": 1, "maxLength": 200,
                             "description": "Optional short secondary label beneath the title. Omit when unnecessary."},
                "payload": {},
                "metadata": {"type": "object", "description": "Optional metadata matching the selected capability's metadataSchema. Omit when no metadata schema is advertised."},
            },
            "required": ["type", "title", "payload"],
        },
    }, execute),), instructions=(
        "Use present_artifact deliberately when a supported presentation helps the user. "
        "Provide complete data matching the selected payload schema. Prefer ordinary text for ordinary answers. "
        "Follow the selected capability's titleDescription and subtitleDescription when provided. "
        "Supply metadata only as advertised by the selected metadataSchema, following its field descriptions. "
        "Presentation does not create or save domain data. Artifacts become visible only when this turn completes.\n"
        "Available presentation capabilities (payload schemas are standalone JSON Schemas):\n"
        + json.dumps([item.model_dump(by_alias=True, exclude_none=True) for item in capabilities], ensure_ascii=False)
    ))
