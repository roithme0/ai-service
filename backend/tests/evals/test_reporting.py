import json
import sys
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.evals.reporting import run_cli


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("passed", 0), ("behavioral_failure", 1), ("execution_error", 2)],
)
def test_cli_writes_and_redacts_explicit_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: str,
    exit_code: int,
    existing: bool,
) -> None:
    path = tmp_path / "nested" / "report.json"
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(path)])

    async def evaluate() -> dict[str, JsonValue]:
        return {"status": status, "calls": ["secret-one", 'secret-"two']}

    if existing:
        path.parent.mkdir()
        path.write_text("stale", encoding="utf-8")

    assert (
        run_cli(evaluate, description=None, secrets=["secret-one", 'secret-"two'])
        == exit_code
    )
    contents = path.read_text(encoding="utf-8")
    assert json.loads(contents)["calls"] == ["[redacted]", "[redacted]"]
    output = capsys.readouterr()
    assert str(path.resolve()) in output.out
    assert "secret-one" not in contents + output.out + output.err
    assert "secret-" not in contents + output.out + output.err


def test_cli_write_failure_is_execution_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(tmp_path)])

    async def evaluate() -> dict[str, JsonValue]:
        return {"status": "passed"}

    assert run_cli(evaluate, description=None) == 2
    assert "Could not write" in capsys.readouterr().err
