"""Tool-call evidence collected from a conversation turn."""

import json
from typing import cast

from pydantic import BaseModel, JsonValue
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from app.capabilities.conversations.observation import TurnObservation
from app.evals.errors import ExecutionError


class CallEvidence(BaseModel):
    tool_name: str
    call_id: str
    arguments: JsonValue
    outcome: str


class Evidence(BaseModel):
    calls: list[CallEvidence]
    error: ExecutionError | None = None


def call_arguments(part: ToolCallPart) -> JsonValue:
    args = part.args
    if isinstance(args, str):
        try:
            return cast(JsonValue, json.loads(args))
        except ValueError:
            return args
    return args


def calls_from_messages(observation: TurnObservation) -> list[CallEvidence]:
    calls: list[CallEvidence] = []
    active: list[CallEvidence] = []
    for message in observation.messages:
        if isinstance(message, ModelResponse):
            active = []
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                call = CallEvidence(
                    tool_name=part.tool_name,
                    call_id=part.tool_call_id,
                    arguments=call_arguments(part),
                    outcome="missing",
                )
                calls.append(call)
                active.append(call)
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                matching = [
                    call
                    for call in active
                    if call.call_id == part.tool_call_id
                    and call.tool_name == part.tool_name
                    and call.outcome == "missing"
                ]
                if len(matching) == 1:
                    matching[0].outcome = (
                        part.outcome if isinstance(part, ToolReturnPart) else "rejected"
                    )
                elif len(matching) > 1:
                    for call in matching:
                        call.outcome = "ambiguous"

    return calls


def reconcile_started_calls(
    calls: list[CallEvidence], observation: TurnObservation
) -> None:
    matched: set[int] = set()
    for part in observation.started_tool_calls:
        args = call_arguments(part)
        existing = next(
            (
                index
                for index, call in enumerate(calls)
                if index not in matched
                and call.tool_name == part.tool_name
                and call.call_id == part.tool_call_id
                and call.arguments == args
                and call.outcome != "rejected"
            ),
            None,
        )
        if existing is None:
            calls.append(
                CallEvidence(
                    tool_name=part.tool_name,
                    call_id=part.tool_call_id,
                    arguments=args,
                    outcome="interrupted",
                )
            )
            matched.add(len(calls) - 1)
        else:
            matched.add(existing)
            if calls[existing].outcome == "missing":
                calls[existing].outcome = "interrupted"


def collect_evidence(observation: TurnObservation) -> Evidence:
    calls = calls_from_messages(observation)
    reconcile_started_calls(calls, observation)
    return Evidence(calls=calls)
