import asyncio
from pathlib import Path

import pytest
from pydantic import JsonValue, SecretStr
from openai.types.shared import ReasoningEffort
from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.capabilities.conversations.observation import TurnObservation
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo.config import LiveConversationDemoSettings
from app.evals import conversation_tool_use as evaluation
from app.evals.evidence import Evidence, collect_evidence


def test_real_greeting_with_function_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    evaluation.TARGET, {"name": "Anna", "language": "de"}, "call-1"
                )
            ]
        )

    def model_factory(
        model_name: str, api_key: SecretStr, *, reasoning_effort: ReasoningEffort = None
    ) -> FunctionModel:
        return FunctionModel(respond)

    monkeypatch.setattr(
        "app.demos.live_conversation_demo.agent.create_openai_model", model_factory
    )
    observation = TurnObservation()
    evidence = asyncio.run(
        evaluation.run_case(
            evaluation.PROMPT,
            observation,
            ProviderSettings(_env_file=None, openai_api_key="test"),
            LiveConversationDemoSettings(_env_file=None, live_demo_openai_model="test"),
        )
    )
    assert len(evidence.calls) == 1
    assert evidence.calls[0].tool_name == evaluation.TARGET
    assert evidence.calls[0].arguments == {"name": "Anna", "language": "de"}
    assert evidence.calls[0].outcome == "success"


@pytest.mark.parametrize(
    ("tool", "arguments", "outcome", "expected"),
    [
        (evaluation.TARGET, {"name": "Anna", "language": "de"}, "success", True),
        (evaluation.TARGET, '{"name":"Anna","language":"de"}', "success", True),
        ("other", {"name": "Anna", "language": "de"}, "success", False),
        (evaluation.TARGET, {"name": "anna", "language": "de"}, "success", False),
        (evaluation.TARGET, {"name": "Anna"}, "success", False),
        (evaluation.TARGET, {"name": "Anna", "language": "de"}, "failed", False),
        (evaluation.TARGET, {"name": "Anna", "language": "de"}, None, False),
    ],
)
def test_grading_requires_corresponding_successful_call(
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    arguments: dict[str, str] | str,
    outcome: str | None,
    expected: bool,
) -> None:
    from pydantic_ai.messages import ModelRequest

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observation.messages.append(
            ModelResponse(parts=[ToolCallPart(tool, arguments, "id")])
        )
        if outcome is not None:
            observation.messages.append(
                ModelRequest(
                    parts=[ToolReturnPart(tool, "result", "id", outcome=outcome)]
                )
            )
        return collect_evidence(observation)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == ("passed" if expected else "behavioral_failure")
    assert report["schema_version"] == 1
    assert report["case"]["input"] == evaluation.PROMPT
    assert report["case"]["target_tool"] == evaluation.TARGET
    assert report["case"]["expected_arguments"] == evaluation.EXPECTED
    assert report["configuration"]["model"] == "test-model"
    assert report["criterion"]["passed"] is expected
    assert report["criterion"]["reason"]
    assert report["calls"][0]["call_id"] == "id"


def test_calls_are_correlated_and_partial_execution_cannot_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ModelRequest

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observation.messages.extend(
            [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            evaluation.TARGET, {"name": "Anna", "language": "de"}, "one"
                        ),
                        ToolCallPart(
                            evaluation.TARGET, {"name": "Bob", "language": "de"}, "two"
                        ),
                    ]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(evaluation.TARGET, "result", "two")]
                ),
            ]
        )
        return collect_evidence(observation)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == "behavioral_failure"
    assert [call["outcome"] for call in report["calls"]] == ["missing", "success"]


def test_partial_matching_execution_remains_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic_ai.messages import ModelRequest

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observation.messages.extend(
            [
                ModelResponse(
                    parts=[ToolCallPart(evaluation.TARGET, evaluation.EXPECTED, "one")]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(evaluation.TARGET, "result", "one")]
                ),
            ]
        )
        raise RuntimeError("test-secret")

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == "execution_error"
    assert report["criterion"] is None
    assert report["calls"][0]["outcome"] == "success"
    assert "test-secret" not in str(report)


@pytest.mark.parametrize("answer", ["Done", "A different final answer"])
def test_extra_calls_do_not_change_grade(
    monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    from pydantic_ai.messages import ModelRequest

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observation.messages.extend(
            [
                ModelResponse(
                    parts=[
                        ToolCallPart("other", {}, "other"),
                        ToolCallPart(evaluation.TARGET, evaluation.EXPECTED, "match"),
                    ]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(evaluation.TARGET, "result", "match")]
                ),
                ModelResponse(parts=[TextPart(answer)]),
            ]
        )
        return collect_evidence(observation)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == "passed"
    assert len(report["calls"]) == 2


@pytest.mark.parametrize(
    "failure", [None, "manager", "client", "agent", "turn", "teardown"]
)
def test_resources_close_on_completion_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    events: list[str] = []

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __aenter__(self) -> "Resource":
            events.append(f"enter {self.name}")
            if failure == self.name:
                raise RuntimeError(self.name)
            return self

        async def __aexit__(self, *args: object) -> None:
            events.append(f"exit {self.name}")
            if failure == "teardown" and self.name == "agent":
                raise ExceptionGroup(
                    "secret", [ValueError("secret"), RuntimeError("secret")]
                )

    manager = Resource("manager")

    class SessionManager:
        def run(self) -> Resource:
            return manager

    class Server:
        session_manager = SessionManager()

    def server_factory() -> tuple[Server, object]:
        return Server(), object()

    def client_factory(*, transport: object) -> Resource:
        return Resource("client")

    def agent_factory(
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
        *,
        mcp_http_client: Resource,
    ) -> Resource:
        return Resource("agent")

    async def turn(
        agent: Resource,
        prompt: str,
        *,
        observation: TurnObservation,
    ) -> None:
        from pydantic_ai.messages import ModelRequest

        observation.messages.extend(
            [
                ModelResponse(
                    parts=[ToolCallPart(evaluation.TARGET, evaluation.EXPECTED, "one")]
                ),
                ModelRequest(
                    parts=[ToolReturnPart(evaluation.TARGET, "result", "one")]
                ),
            ]
        )
        if failure == "turn":
            raise RuntimeError("turn")

    monkeypatch.setattr(evaluation, "create_mcp_server", server_factory)
    monkeypatch.setattr(evaluation, "AsyncClient", client_factory)
    monkeypatch.setattr(
        evaluation, "create_live_conversation_demo_agent", agent_factory
    )
    monkeypatch.setattr(evaluation, "execute_turn", turn)
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")
    report = asyncio.run(evaluation.evaluate())
    if failure is None:
        assert report["status"] == "passed"
    else:
        stages = {
            "manager": "mcp_startup",
            "client": "client_startup",
            "agent": "agent_startup",
            "turn": "turn",
            "teardown": "teardown",
        }
        assert report["status"] == "execution_error"
        assert report["error"]["stage"] == stages[failure]
        assert "secret" not in str(report)
        if failure == "teardown":
            assert report["error"]["type"] == "ExceptionGroup"
            assert set(report["error"]["exception_types"]) == {
                "ExceptionGroup",
                "ValueError",
                "RuntimeError",
            }
            assert report["calls"][0]["outcome"] == "success"
            assert report["criterion"] is None
    assert ("exit manager" in events) == (failure != "manager")
    assert ("exit client" in events) == (failure not in ("manager", "client"))
    assert ("exit agent" in events) == (failure not in ("manager", "client", "agent"))


def test_main_writes_report_for_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json
    import sys

    monkeypatch.setenv("LIVE_DEMO_OPENAI_REASONING_EFFORT", "invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "sensitive-key")
    path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(path)])
    assert evaluation.main() == 2
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["status"] == "execution_error"
    assert report["calls"] == []
    assert report["error"]["stage"] == "configuration"
    assert (
        "sensitive-key"
        not in path.read_text(encoding="utf-8") + capsys.readouterr().out
    )


def test_missing_configuration_has_useful_empty_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def provider_settings() -> ProviderSettings:
        return ProviderSettings(_env_file=None)

    def demo_settings() -> LiveConversationDemoSettings:
        return LiveConversationDemoSettings(_env_file=None)

    monkeypatch.setattr(evaluation, "ProviderSettings", provider_settings)
    monkeypatch.setattr(evaluation, "LiveConversationDemoSettings", demo_settings)
    report = asyncio.run(evaluation.evaluate())
    assert report["schema_version"] == 1
    assert report["status"] == "execution_error"
    assert report["calls"] == []
    assert report["configuration"]["model"] is None
    assert report["configuration"]["reasoning_effort"] == "provider/model default"
    assert report["error"]["type"] == "MissingConfiguration"
    assert report["case"]["input"] == evaluation.PROMPT
    assert report["case"]["target_tool"] == evaluation.TARGET
    assert report["case"]["expected_arguments"] == evaluation.EXPECTED


def test_evaluator_failure_is_execution_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        return Evidence(calls=[])

    def fail_evaluator(
        self: evaluation.GreetingEvaluator,
        ctx: evaluation.EvaluatorContext[str, Evidence, None],
    ) -> bool:
        raise RuntimeError("evaluator failed")

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    monkeypatch.setattr(evaluation.GreetingEvaluator, "evaluate", fail_evaluator)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == "execution_error"
    assert report["error"]["stage"] == "evaluation"
    assert report["criterion"] is None


@pytest.mark.parametrize("completed", [False, True])
def test_retried_call_reusing_id_tracks_valid_occurrence(
    monkeypatch: pytest.MonkeyPatch,
    completed: bool,
) -> None:
    from pydantic_ai.messages import ModelRequest, RetryPromptPart

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        rejected = ToolCallPart(evaluation.TARGET, {"name": "Bob"}, "same")
        valid = ToolCallPart(evaluation.TARGET, evaluation.EXPECTED, "same")
        observation.messages.extend(
            [
                ModelResponse(parts=[rejected]),
                ModelRequest(
                    parts=[
                        RetryPromptPart(
                            "missing language",
                            tool_name=evaluation.TARGET,
                            tool_call_id="same",
                        )
                    ]
                ),
                ModelResponse(parts=[valid]),
            ]
        )
        observation.started_tool_calls = (valid,)
        if completed:
            observation.messages.append(
                ModelRequest(
                    parts=[ToolReturnPart(evaluation.TARGET, "result", "same")]
                )
            )
        return collect_evidence(observation)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == ("passed" if completed else "behavioral_failure")
    calls = report["calls"]
    assert len(calls) == 2
    assert calls[0]["arguments"] == {"name": "Bob"}
    assert calls[0]["outcome"] == "rejected"
    assert calls[1]["arguments"] == evaluation.EXPECTED
    assert calls[1]["outcome"] == ("success" if completed else "interrupted")


def test_completed_run_without_calls_is_behavioral_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observation.messages.append(ModelResponse(parts=[TextPart("Welcome")]))
        return collect_evidence(observation)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    report = asyncio.run(evaluation.evaluate())
    assert report["status"] == "behavioral_failure"
    assert report["calls"] == []
    assert report["criterion"]["passed"] is False


def test_each_task_uses_its_own_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LIVE_DEMO_OPENAI_MODEL", "test-model")
    observations: list[TurnObservation] = []
    original_evaluate = evaluation.Dataset.evaluate

    async def fake_run(
        prompt: str,
        observation: TurnObservation,
        provider: ProviderSettings,
        settings: LiveConversationDemoSettings,
    ) -> Evidence:
        observations.append(observation)
        assert observation.messages == []
        observation.messages.append(ModelResponse(parts=[TextPart(prompt)]))
        return collect_evidence(observation)

    async def evaluate_twice(
        self: evaluation.Dataset[str, Evidence, None], task: object, **kwargs: object
    ) -> object:
        # Exercise the dataset's task independently before its normal execution.
        from collections.abc import Awaitable, Callable
        from typing import cast

        run = cast(Callable[[str], Awaitable[Evidence]], task)
        await run("first")
        await run("second")
        return await original_evaluate(self, run, progress=False)

    monkeypatch.setattr(evaluation, "run_case", fake_run)
    monkeypatch.setattr(evaluation.Dataset, "evaluate", evaluate_twice)
    asyncio.run(evaluation.evaluate())
    assert len(observations) == 3
    assert len({id(observation) for observation in observations}) == 3


def test_main_redacts_configured_provider_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    secret = "sensitive-provider-key"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    path = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(path)])

    async def fake_evaluate() -> dict[str, JsonValue]:
        return {"status": "passed", "calls": [secret]}

    monkeypatch.setattr(evaluation, "evaluate", fake_evaluate)
    assert evaluation.main() == 0
    assert secret not in path.read_text(encoding="utf-8") + capsys.readouterr().out
