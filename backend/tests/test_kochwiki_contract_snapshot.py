import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from scripts import kochwiki_contract as contract

COMMIT = "a" * 40


def export() -> str:
    return json.dumps({
        "openapi": "3.1.0",
        "paths": {"/recipe-presentations/resolve": {"post": {"responses": {
            "200": {"content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/RecipePresentationOut",
            }}}},
        }}}},
        "components": {"schemas": {
            name: {"additionalProperties": False} for name in (
                "RecipePresentationOut", "RecipePresentationIngredientOut",
                "RecipePresentationStepOut", "FoodstuffSummaryOut",
            )
        }},
    }, indent=2) + "\n"


class Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *arguments: object) -> None:
        pass

    def read(self) -> bytes:
        return self.content


def respond(monkeypatch: pytest.MonkeyPatch, content: str) -> list[str]:
    urls: list[str] = []

    def fetch(url: str, timeout: float) -> Response:
        assert timeout == 20
        urls.append(url)
        return Response(content.encode("utf-8"))

    monkeypatch.setattr(contract, "urlopen", fetch)
    return urls


def test_update_and_check_use_only_the_explicit_github_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    urls = respond(monkeypatch, export())
    contract.update_snapshot(COMMIT.upper(), tmp_path)
    provenance = json.loads((tmp_path / "provenance.json").read_text())
    assert provenance == {
        "repository": contract.REPOSITORY, "commit_sha": COMMIT, "source_path": contract.SOURCE_PATH,
    }
    first = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    contract.update_snapshot(COMMIT, tmp_path)
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == first
    assert contract.check_snapshot(tmp_path) == COMMIT
    assert urls == [f"https://raw.githubusercontent.com/roithme0/Kochwiki-v2/{COMMIT}/{contract.SOURCE_PATH}"] * 3


@pytest.mark.parametrize("revision", ["main", "v1.0.0", "39f3f97", "g" * 40, "../" + "a" * 40])
def test_unpinned_revision_is_rejected_before_network_or_file_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, revision: str,
) -> None:
    urls = respond(monkeypatch, export())
    with pytest.raises(contract.ContractError, match="full 40-character"):
        contract.update_snapshot(revision, tmp_path)
    assert urls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["network", "404", "json", "schema"])
def test_failed_update_preserves_previous_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    respond(monkeypatch, export())
    contract.update_snapshot(COMMIT, tmp_path)
    previous = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    if failure in ("network", "404"):
        def fail(url: str, timeout: float) -> Response:
            if failure == "404":
                raise HTTPError(url, 404, "Not Found", {}, None)
            raise URLError("unavailable")
        monkeypatch.setattr(contract, "urlopen", fail)
    else:
        respond(monkeypatch, "invalid" if failure == "json" else export().replace("false", "true"))
    with pytest.raises(contract.ContractError):
        contract.update_snapshot("b" * 40, tmp_path)
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == previous


@pytest.mark.parametrize("mutation", ["missing_snapshot", "missing_provenance", "malformed_json", "repository", "source_path", "commit_sha"])
def test_missing_or_invalid_local_files_fail_before_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str,
) -> None:
    urls = respond(monkeypatch, export())
    contract.update_snapshot(COMMIT, tmp_path)
    if mutation.startswith("missing"):
        name = "openapi.json" if mutation == "missing_snapshot" else "provenance.json"
        (tmp_path / name).unlink()
    elif mutation == "malformed_json":
        (tmp_path / "provenance.json").write_text("{", encoding="utf-8")
    else:
        path = tmp_path / "provenance.json"
        provenance = json.loads(path.read_text())
        provenance[mutation] = "invalid"
        path.write_text(json.dumps(provenance), encoding="utf-8")
    urls.clear()
    with pytest.raises(contract.ContractError):
        contract.check_snapshot(tmp_path)
    assert urls == []


def test_check_rejects_content_drift_without_rewriting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    respond(monkeypatch, export())
    contract.update_snapshot(COMMIT, tmp_path)
    path = tmp_path / "openapi.json"
    changed = export().replace('3.1.0', '3.0.0')
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(contract.ContractError, match="differs from pinned"):
        contract.check_snapshot(tmp_path)
    assert path.read_text() == changed


def test_check_accepts_git_line_ending_conversion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    respond(monkeypatch, export())
    contract.update_snapshot(COMMIT, tmp_path)
    (tmp_path / "openapi.json").write_bytes(export().replace("\n", "\r\n").encode())
    assert contract.check_snapshot(tmp_path) == COMMIT


def test_cli_returns_clear_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def fail() -> str:
        raise contract.ContractError("snapshot missing")
    monkeypatch.setattr(contract, "check_snapshot", fail)
    assert contract.main(["check"]) == 1
    assert capsys.readouterr().err == "Kochwiki contract: snapshot missing\n"
