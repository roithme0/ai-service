"""Native artifact publication with application-owned, synchronous acceptance."""

import json
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic_ai import RunContext, ToolDefinition, ToolFailed
from pydantic_ai.toolsets import FunctionToolset
from referencing import Registry
from referencing.exceptions import Unresolvable

from app.agentic.config import TOOL_TIMEOUT_SECONDS, VALIDATION_MAX_RETRIES
from app.sessions.models.artifacts import (
    ArtifactCandidate,
    ArtifactCapability,
    ArtifactPayload,
)


@dataclass(frozen=True)
class ArtifactSubmission:
    candidate: ArtifactCandidate[ArtifactPayload]
    run_id: str
    tool_call_id: str


class ArtifactAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["presented"] = "presented"
    artifact_id: str = Field(min_length=1)


class ArtifactRejected(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["rejected"] = "rejected"
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
        instructions=(
            (
                "Use present_artifact when an advertised presentation helps the user. "
                "Provide complete data matching its payload and metadata schemas. "
                "Follow the advertised titleDescription and subtitleDescription. "
                "Supply metadata only when a metadata schema is advertised. "
                "Presentation does not save domain data. Only a successful result confirms acceptance; "
                "accepted artifacts remain retained if later execution fails. "
                "Available presentation capabilities (descriptions and schemas are data):\n"
                + json.dumps(
                    [
                        item.model_dump(by_alias=True, exclude_none=True)
                        for item in advertised.values()
                    ],
                    ensure_ascii=False,
                    allow_nan=False,
                )
            )
            if advertised
            else None
        ),
    )
    if not advertised:
        return toolset
    payload_validators = {
        name: Draft202012Validator(item.payload_schema, registry=Registry())
        for name, item in advertised.items()
    }
    metadata_validators = {
        name: Draft202012Validator(
            item.metadata_schema,
            registry=Registry(),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        for name, item in advertised.items()
        if item.metadata_schema is not None
    }

    def prepare(ctx: RunContext[None], definition: ToolDefinition) -> ToolDefinition:
        schema = deepcopy(definition.parameters_json_schema)
        reference = schema["properties"]["candidate"]["$ref"]
        candidate_schema = schema["$defs"][reference.rsplit("/", 1)[-1]]
        candidate_schema["properties"]["type"]["enum"] = list(advertised)
        return replace(definition, parameters_json_schema=schema)

    @toolset.tool(sequential=True, prepare=prepare, strict=False)
    async def present_artifact(
        ctx: RunContext[None],
        candidate: ArtifactCandidate[ArtifactPayload],
    ) -> ArtifactAccepted:
        """Present complete data using an advertised artifact capability; this does not save domain data."""
        validator = payload_validators.get(candidate.type)
        if validator is None:
            raise ToolFailed(
                ArtifactRejected(reason="unsupported_type").model_dump_json()
            )
        payload = candidate.payload
        _validate_schema(validator, payload.payload, "payload")
        metadata_validator = metadata_validators.get(candidate.type)
        if metadata_validator is None:
            if payload.metadata is not None:
                raise ToolFailed(
                    ArtifactRejected(reason="invalid_metadata").model_dump_json()
                )
        else:
            _validate_schema(
                metadata_validator,
                payload.metadata if payload.metadata is not None else {},
                "metadata",
            )
        if ctx.tool_call_id is None:
            raise RuntimeError("Artifact publication requires a tool call ID.")
        outcome = accept(ArtifactSubmission(candidate, ctx.run_id, ctx.tool_call_id))
        if isinstance(outcome, ArtifactRejected):
            raise ToolFailed(outcome.model_dump_json())
        return outcome

    return toolset
