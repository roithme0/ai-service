"""Standalone, single-case evaluation of the live demo's greeting tool."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from httpx2 import ASGITransport, AsyncClient
from pydantic import BaseModel, JsonValue
from pydantic_ai.messages import (
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from starlette.applications import Starlette
from starlette.routing import Mount

from app.capabilities.conversations.observation import TurnObservation
from app.capabilities.conversations.turns import execute_turn
from app.core.config import ProviderSettings
from app.demos.live_conversation_demo.agent import create_live_conversation_demo_agent
from app.demos.live_conversation_demo.config import LiveConversationDemoSettings
from app.demos.live_conversation_demo.mcp.server import create_mcp_server

PROMPT = "Use the greeting tool to welcome Anna in German."
TARGET = "greetings__greet"
EXPECTED = {"name": "Anna", "language": "de"}


class CallEvidence(BaseModel):
    tool_name: str
    call_id: str
    arguments: JsonValue
    outcome: str


class ExecutionError(BaseModel):
    stage: str
    type: str
    exception_types: list[str]
    message: str


class Evidence(BaseModel):
    calls: list[CallEvidence]
    error: ExecutionError | None = None


class CaseExecutionError(Exception):
    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(stage)
        self.stage = stage
        self.error = error


def exception_types(error: BaseException) -> list[str]:
    name = type(error).__name__
    safe_name = name if name.isidentifier() and len(name) <= 100 else "UnknownError"
    names = [safe_name]
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            names.extend(exception_types(nested))
    return names


def wrapped_execution_error(error: BaseException) -> CaseExecutionError | None:
    if isinstance(error, CaseExecutionError):
        return error
    if isinstance(error, BaseExceptionGroup) and len(error.exceptions) == 1:
        return wrapped_execution_error(error.exceptions[0])
    return None


ERROR_MESSAGES = {
    "mcp_startup": "Could not start the in-process greeting server.",
    "client_startup": "Could not start the in-process MCP client.",
    "agent_startup": "Could not start the live-demo agent; inspect its configuration.",
    "turn": "The agent turn failed; inspect provider connectivity and limits.",
    "teardown": "Could not close evaluation resources cleanly.",
}


@dataclass
class GreetingEvaluator(Evaluator[str, Evidence, None]):
    def evaluate(self, ctx: EvaluatorContext[str, Evidence, None]) -> bool:
        return any(
            call.tool_name == TARGET
            and call.outcome == "success"
            and isinstance(call.arguments, dict)
            and all(call.arguments.get(key) == value for key, value in EXPECTED.items())
            for call in ctx.output.calls
        )


def call_arguments(part: ToolCallPart) -> JsonValue:
    args = part.args
    if isinstance(args, str):
        try:
            return json.loads(args)
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


async def run_case(
    prompt: str,
    observation: TurnObservation,
    provider: ProviderSettings,
    settings: LiveConversationDemoSettings,
) -> Evidence:
    stage = "mcp_startup"
    try:
        async with AsyncExitStack() as stack:
            try:
                server, mcp_app = create_mcp_server()
                application = Starlette(routes=[Mount("/mcp", app=mcp_app)])
                await stack.enter_async_context(server.session_manager.run())
                stage = "client_startup"
                client = await stack.enter_async_context(
                    AsyncClient(transport=ASGITransport(app=application))
                )
                stage = "agent_startup"
                agent = create_live_conversation_demo_agent(
                    provider, settings, mcp_http_client=client
                )
                await stack.enter_async_context(agent)
                stage = "turn"
                await execute_turn(agent, prompt, observation=observation)
            except Exception as exc:
                raise CaseExecutionError(stage, exc) from None
    except CaseExecutionError:
        raise
    except Exception as exc:
        wrapped = wrapped_execution_error(exc)
        if wrapped is not None:
            raise wrapped from None
        raise CaseExecutionError("teardown", exc) from None

    return collect_evidence(observation)


async def evaluate() -> dict[str, JsonValue]:
    observation = TurnObservation()
    report: dict[str, JsonValue] = {
        "schema_version": 1,
        "case": {
            "name": "greeting_anna_german",
            "input": PROMPT,
            "target_tool": TARGET,
            "expected_arguments": EXPECTED,
        },
        "configuration": {"model": None, "reasoning_effort": "provider/model default"},
        "calls": [],
        "status": "execution_error",
        "criterion": None,
        "error": None,
    }
    stage = "configuration"
    try:
        settings = LiveConversationDemoSettings()
        report["configuration"] = {
            "model": settings.live_demo_openai_model,
            "reasoning_effort": settings.live_demo_openai_reasoning_effort
            or "provider/model default",
        }
        provider = ProviderSettings()
        missing = []
        if (
            provider.openai_api_key is None
            or not provider.openai_api_key.get_secret_value().strip()
        ):
            missing.append("OPENAI_API_KEY")
        if settings.live_demo_openai_model is None:
            missing.append("LIVE_DEMO_OPENAI_MODEL")
        if missing:
            report["error"] = {
                "stage": "configuration",
                "type": "MissingConfiguration",
                "message": "Missing: " + ", ".join(missing),
            }
            return report
        stage = "execution"
        dataset: Dataset[str, Evidence, None] = Dataset(
            name="conversation_tool_use",
            cases=[Case(name="greeting_anna_german", inputs=PROMPT)],
            evaluators=[GreetingEvaluator()],
        )

        async def task(prompt: str) -> Evidence:
            try:
                return await run_case(prompt, observation, provider, settings)
            except CaseExecutionError as exc:
                evidence = collect_evidence(observation)
                names = exception_types(exc.error)
                evidence.error = ExecutionError(
                    stage=exc.stage,
                    type=names[0],
                    exception_types=names,
                    message=ERROR_MESSAGES[exc.stage],
                )
                return evidence

        result = await dataset.evaluate(task, progress=False)
        report["calls"] = collect_evidence(observation).model_dump(mode="json")["calls"]
        if result.failures:
            report["error"] = {
                "stage": stage,
                "type": "TaskFailure",
                "message": "The evaluation task could not complete; inspect configuration and provider connectivity.",
            }
        elif len(result.cases) == 1 and result.cases[0].output.error is not None:
            error = result.cases[0].output.error
            assert error is not None
            report["error"] = error.model_dump(mode="json")
        elif (
            len(result.cases) != 1
            or result.cases[0].evaluator_failures
            or "GreetingEvaluator" not in result.cases[0].assertions
        ):
            report["error"] = {
                "stage": "evaluation",
                "type": "EvaluatorFailure",
                "message": "The deterministic evaluator could not complete.",
            }
        else:
            passed = result.cases[0].assertions["GreetingEvaluator"].value
            report["criterion"] = {
                "passed": passed,
                "reason": (
                    "Successful matching greeting execution observed."
                    if passed
                    else "No successful matching greeting execution observed."
                ),
            }
            report["status"] = "passed" if passed else "behavioral_failure"
    except Exception as exc:
        report["calls"] = collect_evidence(observation).model_dump(mode="json")["calls"]
        report["error"] = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": "The evaluation could not complete; inspect configuration and provider connectivity.",
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate())
    # Redact even if a provider happens to echo a credential in tool arguments.
    try:
        secret = ProviderSettings().openai_api_key
    except Exception:
        secret = None
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if secret and secret.get_secret_value():
        serialized = serialized.replace(
            json.dumps(secret.get_secret_value(), ensure_ascii=False)[1:-1],
            "[redacted]",
        )
    print(serialized)
    try:
        path = args.report.resolve()
        print(f"Report: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized + "\n", encoding="utf-8")
    except OSError:
        print("Could not write evaluation report.", file=sys.stderr)
        return 2
    return {"passed": 0, "behavioral_failure": 1, "execution_error": 2}[
        str(report["status"])
    ]


if __name__ == "__main__":
    sys.exit(main())
