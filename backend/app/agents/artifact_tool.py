"""Agent tool for producing artifacts from advertised artifact capabilities."""

from __future__ import annotations

import json
from typing import Literal

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import Unresolvable
from pydantic import JsonValue, ValidationError

from app.agents.instructions import ARTIFACT_TOOL_INSTRUCTIONS
from app.agents.models.artifacts import ArtifactRequest
from app.agents.models.tools import RegisteredTool, ToolInvocation
from app.agents.models.tools import LocalToolSource
from app.sessions.config import MAX_ARTIFACT_HEADER_LENGTH
from app.sessions.models.artifacts import ArtifactCandidate, ArtifactCapability, ArtifactPayload, ArtifactToolOutput
from app.sessions.models.execution import ToolExecution


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


def _artifact_tool_schema(capabilities: tuple[ArtifactCapability, ...]) -> dict[str, object]:
    return {
        "type": "function", "name": "present_artifact", "strict": False,
        "description": "Present complete data to the user using an advertised artifact capability. This has no domain save effect.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": [item.type for item in capabilities]},
                "title": {"type": "string", "minLength": 1, "maxLength": MAX_ARTIFACT_HEADER_LENGTH},
                "subtitle": {"type": ["string", "null"], "minLength": 1, "maxLength": MAX_ARTIFACT_HEADER_LENGTH,
                             "description": "Optional short secondary label beneath the title. Omit when unnecessary."},
                "payload": {},
                "metadata": {"type": "object", "description": "Optional metadata matching the selected capability's metadataSchema. Omit when no metadata schema is advertised."},
            },
            "required": ["type", "title", "payload"],
        },
    }


def _artifact_tool_instructions(capabilities: tuple[ArtifactCapability, ...]) -> str:
    return ARTIFACT_TOOL_INSTRUCTIONS + json.dumps(
        [item.model_dump(by_alias=True, exclude_none=True) for item in capabilities], ensure_ascii=False,
    )


def artifact_tool_source(
    capabilities: tuple[ArtifactCapability, ...],
) -> LocalToolSource[ArtifactCandidate[ArtifactPayload]]:
    validators = {item.type: Draft202012Validator(item.payload_schema, registry=Registry()) for item in capabilities}
    metadata_validators = {item.type: Draft202012Validator(item.metadata_schema, registry=Registry(),
                           format_checker=Draft202012Validator.FORMAT_CHECKER)
                           for item in capabilities if item.metadata_schema is not None}

    def execute(call: ToolInvocation) -> ToolExecution[ArtifactCandidate[ArtifactPayload]]:
        try:
            request = ArtifactRequest.model_validate_json(call.arguments)
            json.dumps(request.payload, allow_nan=False)
            json.dumps(request.metadata, allow_nan=False)
        except (ValidationError, ValueError, RecursionError):
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_arguments"}), failed=True)
        validator = validators.get(request.type)
        if validator is None:
            return ToolExecution(json.dumps({"kind": "rejected", "reason": "unsupported_type"}), failed=True)
        rejection = _schema_rejection(validator, request.payload, "payload")
        if rejection is not None:
            return ToolExecution(rejection, failed=True)
        metadata_validator = metadata_validators.get(request.type)
        if metadata_validator is None:
            if request.metadata is not None:
                return ToolExecution(json.dumps({"kind": "rejected", "reason": "invalid_metadata",
                                                 "detail": "This capability does not advertise metadata"}), failed=True)
        else:
            rejection = _schema_rejection(metadata_validator, request.metadata or {}, "metadata")
            if rejection is not None:
                return ToolExecution(rejection, failed=True)
        candidate = ArtifactCandidate(request.type,
            ArtifactPayload(title=request.title, subtitle=request.subtitle, payload=request.payload,
                                metadata=request.metadata))
        return ToolExecution(ArtifactToolOutput("presented"), candidate)

    return LocalToolSource(
        (RegisteredTool("present_artifact", _artifact_tool_schema(capabilities), execute),),
        instructions=_artifact_tool_instructions(capabilities),
    )
