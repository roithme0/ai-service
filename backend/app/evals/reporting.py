"""Common command-line reporting for standalone evaluations."""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from pydantic import JsonValue


def run_cli(
    evaluate: Callable[[], Awaitable[dict[str, JsonValue]]],
    *,
    description: str | None,
    secrets: Iterable[str] = (),
) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate())
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    for secret in secrets:
        if secret:
            serialized = serialized.replace(
                json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]"
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
