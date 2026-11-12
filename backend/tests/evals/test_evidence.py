from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart

from app.capabilities.conversations.observation import TurnObservation
from app.evals.evidence import collect_evidence

TARGET = "example__tool"
EXPECTED = {"name": "Anna", "language": "de"}


def test_started_unfinished_call_is_interrupted() -> None:
    observation = TurnObservation()
    call = ToolCallPart(TARGET, EXPECTED, "one")
    observation.messages.append(ModelResponse(parts=[call]))
    observation.started_tool_calls = (call,)
    assert collect_evidence(observation).calls[0].outcome == "interrupted"


def test_sequential_reused_call_ids_keep_occurrences_distinct() -> None:
    from pydantic_ai.messages import ModelRequest

    observation = TurnObservation()
    observation.messages.extend(
        [
            ModelResponse(parts=[ToolCallPart(TARGET, EXPECTED, "same")]),
            ModelRequest(parts=[ToolReturnPart(TARGET, "first", "same")]),
            ModelResponse(
                parts=[ToolCallPart(TARGET, {"name": "Bob", "language": "de"}, "same")]
            ),
            ModelRequest(parts=[ToolReturnPart(TARGET, "second", "same")]),
        ]
    )
    calls = collect_evidence(observation).calls
    assert [(call.arguments, call.outcome) for call in calls] == [
        (EXPECTED, "success"),
        ({"name": "Bob", "language": "de"}, "success"),
    ]


def test_simultaneous_reused_call_ids_are_not_misattributed() -> None:
    from pydantic_ai.messages import ModelRequest

    observation = TurnObservation()
    observation.messages.extend(
        [
            ModelResponse(
                parts=[
                    ToolCallPart(TARGET, EXPECTED, "same"),
                    ToolCallPart(TARGET, {"name": "Bob", "language": "de"}, "same"),
                ]
            ),
            ModelRequest(parts=[ToolReturnPart(TARGET, "result", "same")]),
        ]
    )
    calls = collect_evidence(observation).calls
    assert all(call.outcome != "success" for call in calls)
