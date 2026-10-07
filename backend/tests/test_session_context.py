import json

import pytest

from app.agents.models.input import AgentInputAccepted, AgentInputRejected
from app.agents.context import CONTEXT_PREFIX, MAX_CONTEXT_LENGTH, validate_context_input


def test_retains_json_values_without_domain_validation_or_shared_mutable_state() -> None:
    data = {"context": {"source": {"external_reference": "not-a-uuid"},
                        "values": [None, True, 1, 1.25, "125.750", {"name": "Öl"}]}}
    outcome = validate_context_input(data)
    assert isinstance(outcome, AgentInputAccepted)
    retained = outcome.context.model_context
    assert retained.startswith(CONTEXT_PREFIX)
    assert json.loads(retained[len(CONTEXT_PREFIX):]) == data["context"]
    data["context"]["values"].append("changed")
    assert outcome.context.model_context == retained


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), object(), (1, 2)])
def test_rejects_values_that_are_not_valid_json(value: object) -> None:
    assert isinstance(validate_context_input({"context": {"nested": [value]}}), AgentInputRejected)


def test_limit_counts_the_actual_model_context_including_the_prefix() -> None:
    overhead = len(CONTEXT_PREFIX) + len('{"text":""}')
    payload = {"context": {"text": "x" * (MAX_CONTEXT_LENGTH - overhead)}}
    accepted = validate_context_input(payload)
    assert isinstance(accepted, AgentInputAccepted)
    assert len(accepted.context.model_context) == MAX_CONTEXT_LENGTH
    payload["context"]["text"] += "x"
    rejected = validate_context_input(payload)
    assert isinstance(rejected, AgentInputRejected)
    assert rejected.issues[0].location == ("context",)


def test_capabilities_are_detached_from_the_callers_mutable_schema() -> None:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    outcome = validate_context_input({"context": {}, "artifactCapabilities": [{
        "type": "example", "description": "Show an example", "payloadSchema": schema,
    }]})
    assert isinstance(outcome, AgentInputAccepted)
    schema["properties"]["name"]["type"] = "number"
    assert outcome.context.artifact_capabilities[0].payload_schema["properties"] == {"name": {"type": "string"}}


@pytest.mark.parametrize("field", ["titleDescription", "subtitleDescription"])
def test_header_guidance_is_retained_without_requiring_it(field: str) -> None:
    capability = {"type": "example", "description": "Show an example", "payloadSchema": {},
                  field: "Use the supplied name or brand."}
    outcome = validate_context_input({"context": {}, "artifactCapabilities": [capability]})
    assert isinstance(outcome, AgentInputAccepted)
    assert outcome.context.artifact_capabilities[0].model_dump(by_alias=True)[field] == capability[field]


@pytest.mark.parametrize("field", ["titleDescription", "subtitleDescription"])
@pytest.mark.parametrize("value", ["", "   ", "x" * 2001, 42])
def test_invalid_header_guidance_is_rejected(field: str, value: object) -> None:
    outcome = validate_context_input({"context": {}, "artifactCapabilities": [{
        "type": "example", "description": "Show an example", "payloadSchema": {}, field: value,
    }]})
    assert isinstance(outcome, AgentInputRejected)
    assert outcome.issues[0].location == ("artifactCapabilities", 0, field)
