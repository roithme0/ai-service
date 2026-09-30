"""Update and verify the pinned Kochwiki OpenAPI snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from urllib.error import URLError
from urllib.request import urlopen

REPOSITORY = "https://github.com/roithme0/Kochwiki-v2"
SOURCE_PATH = "frontend/src/app/core/api/generated/openapi.json"
CONTRACT_DIRECTORY = Path(__file__).resolve().parents[1] / "contracts" / "kochwiki"


class ContractError(Exception):
    pass


def full_commit(value: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{40}", value) is None:
        raise ContractError("Expected a full 40-character Git commit SHA, not a branch, tag, or abbreviated SHA.")
    return value.lower()


def json_object(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{description} must be a JSON object.")
    return cast(dict[str, object], value)


def parse_object(content: str, description: str) -> dict[str, object]:
    try:
        parsed: object = json.loads(content)
    except ValueError as error:
        raise ContractError(f"{description} is not valid JSON.") from error
    return json_object(parsed, description)


def validate_export(content: str) -> None:
    document = parse_object(content, "OpenAPI snapshot")
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise ContractError("Expected an OpenAPI 3 document.")
    paths = json_object(document.get("paths"), "OpenAPI paths")
    route = json_object(paths.get("/recipe-presentations/resolve"), "Resolver route")
    operation = json_object(route.get("post"), "Resolver POST operation")
    responses = json_object(operation.get("responses"), "Resolver responses")
    success = json_object(responses.get("200"), "Resolver success response")
    content_types = json_object(success.get("content"), "Resolver success content")
    media = json_object(content_types.get("application/json"), "Resolver JSON response")
    schema = json_object(media.get("schema"), "Resolver response schema")
    if schema.get("$ref") != "#/components/schemas/RecipePresentationOut":
        raise ContractError("Resolver success response must reference RecipePresentationOut.")
    components = json_object(document.get("components"), "OpenAPI components")
    schemas = json_object(components.get("schemas"), "OpenAPI schemas")
    for name in (
        "RecipePresentationOut", "RecipePresentationIngredientOut",
        "RecipePresentationStepOut", "FoodstuffSummaryOut",
    ):
        model = json_object(schemas.get(name), name)
        if model.get("additionalProperties") is not False:
            raise ContractError(f"{name} must forbid undocumented fields. Select a revision with the completed resolver schema.")


def fetch_export(commit: str) -> str:
    revision = full_commit(commit)
    url = f"https://raw.githubusercontent.com/roithme0/Kochwiki-v2/{revision}/{SOURCE_PATH}"
    try:
        with urlopen(url, timeout=20) as response:
            content = response.read().decode("utf-8").replace("\r\n", "\n")
    except (URLError, TimeoutError, OSError, UnicodeError) as error:
        raise ContractError(f"Could not fetch Kochwiki OpenAPI at {revision}: {error}") from error
    validate_export(content)
    return content


def update_snapshot(commit: str, directory: Path = CONTRACT_DIRECTORY) -> None:
    revision = full_commit(commit)
    document = fetch_export(revision)
    provenance = json.dumps({
        "repository": REPOSITORY,
        "commit_sha": revision,
        "source_path": SOURCE_PATH,
    }, indent=2) + "\n"
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".update-", dir=directory) as temporary:
        staged = Path(temporary)
        for name, content in (("openapi.json", document), ("provenance.json", provenance)):
            (staged / name).write_text(content, encoding="utf-8", newline="\n")
        for name in ("openapi.json", "provenance.json"):
            os.replace(staged / name, directory / name)


def check_snapshot(directory: Path = CONTRACT_DIRECTORY) -> str:
    try:
        provenance_text = (directory / "provenance.json").read_text(encoding="utf-8")
        document = (directory / "openapi.json").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractError(f"Could not read snapshot files in {directory}. Run update --commit <full-SHA>.") from error
    provenance = parse_object(provenance_text, "Snapshot provenance")
    if set(provenance) != {"repository", "commit_sha", "source_path"}:
        raise ContractError("Snapshot provenance must contain repository, commit_sha, and source_path.")
    if provenance["repository"] != REPOSITORY or provenance["source_path"] != SOURCE_PATH:
        raise ContractError("Snapshot provenance does not identify the expected Kochwiki GitHub source.")
    commit = provenance["commit_sha"]
    if not isinstance(commit, str):
        raise ContractError("Snapshot provenance commit_sha must be a full Git commit SHA.")
    revision = full_commit(commit)
    validate_export(document)
    upstream = fetch_export(revision)
    if document.replace("\r\n", "\n") != upstream:
        raise ContractError(f"Kochwiki snapshot differs from pinned commit {revision}. Run update --commit {revision}.")
    return revision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("update", help="Fetch the export at an explicit full GitHub commit SHA.")
    update.add_argument("--commit", required=True)
    commands.add_parser("check", help="Compare the snapshot with its recorded GitHub revision.")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "update":
            update_snapshot(arguments.commit)
            print(f"Kochwiki snapshot updated to {full_commit(arguments.commit)}.")
        else:
            revision = check_snapshot()
            print(f"Kochwiki snapshot matches pinned commit {revision}.")
    except (ContractError, OSError) as error:
        print(f"Kochwiki contract: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
