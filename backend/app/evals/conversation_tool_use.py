"""Standalone, single-case evaluation of the live demo's greeting tool."""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass

from httpx2 import ASGITransport, AsyncClient
from pydantic import JsonValue
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from starlette.applications import Starlette
from starlette.routing import Mount

from app.capabilities.conversations.observation import TurnObservation
from app.capabilities.conversations.turns import execute_turn
from app.core.config import ProviderSettings
from app.evals.errors import (
    CaseExecutionError,
    ExecutionError,
    exception_types,
    wrapped_execution_error,
)
from app.evals.evidence import Evidence, collect_evidence
from app.evals.reporting import run_cli
from app.demos.live_conversation_demo.agent import create_live_conversation_demo_agent
from app.demos.live_conversation_demo.config import LiveConversationDemoSettings
from app.demos.live_conversation_demo.mcp.server import create_mcp_server

PROMPT = "Use the greeting tool to welcome Anna in German."
TARGET = "greetings__greet"
EXPECTED = {"name": "Anna", "language": "de"}


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
    observations: list[TurnObservation] = []
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

    def recorded_calls() -> list[JsonValue]:
        return [
            call.model_dump(mode="json")
            for observation in observations
            for call in collect_evidence(observation).calls
        ]

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
            observation = TurnObservation()
            observations.append(observation)
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
        report["calls"] = recorded_calls()
        if result.failures:
            report["error"] = {
                "stage": stage,
                "type": "TaskFailure",
                "message": "The evaluation task could not complete; inspect configuration and provider connectivity.",
            }
            return report

        if len(result.cases) != 1:
            report["error"] = {
                "stage": "evaluation",
                "type": "EvaluatorFailure",
                "message": "The deterministic evaluator could not complete.",
            }
            return report

        case = result.cases[0]
        if case.output.error is not None:
            report["error"] = case.output.error.model_dump(mode="json")
        elif case.evaluator_failures or "GreetingEvaluator" not in case.assertions:
            report["error"] = {
                "stage": "evaluation",
                "type": "EvaluatorFailure",
                "message": "The deterministic evaluator could not complete.",
            }
        else:
            passed = case.assertions["GreetingEvaluator"].value
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
        report["calls"] = recorded_calls()
        report["error"] = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": "The evaluation could not complete; inspect configuration and provider connectivity.",
        }
    return report


def main() -> int:
    try:
        secret = ProviderSettings().openai_api_key
    except Exception:
        secret = None
    return run_cli(
        evaluate,
        description=__doc__,
        secrets=[secret.get_secret_value()] if secret else [],
    )


if __name__ == "__main__":
    sys.exit(main())
