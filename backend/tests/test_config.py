from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def clear_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KOCHWIKI_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("KOCHWIKI_OPENAI_REASONING_EFFORT", raising=False)


def test_settings_are_optional_when_provider_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_provider_environment(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.openai_api_key is None
    assert settings.kochwiki_openai_model is None
    assert settings.kochwiki_openai_reasoning_effort is None


def test_settings_load_and_normalize_an_explicit_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_provider_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=secret-key\n"
        "KOCHWIKI_OPENAI_MODEL=  gpt-test  \n"
        "KOCHWIKI_OPENAI_REASONING_EFFORT=  high  \n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "secret-key"
    assert settings.kochwiki_openai_model == "gpt-test"
    assert settings.kochwiki_openai_reasoning_effort == "high"


def test_blank_settings_are_treated_as_unset() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="   ",
        kochwiki_openai_model=" ",
        kochwiki_openai_reasoning_effort=" ",
    )

    assert settings.openai_api_key is None
    assert settings.kochwiki_openai_model is None
    assert settings.kochwiki_openai_reasoning_effort is None


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max", "", "   "])
def test_reasoning_effort_from_process_environment(
    monkeypatch: pytest.MonkeyPatch, effort: str,
) -> None:
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", effort)
    settings = Settings(_env_file=None)

    assert settings.kochwiki_openai_reasoning_effort == (effort.strip() or None)


@pytest.mark.parametrize("effort", ["invalid", "HIGH", "default"])
def test_unknown_reasoning_effort_is_rejected(
    monkeypatch: pytest.MonkeyPatch, effort: str,
) -> None:
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", effort)

    with pytest.raises(ValidationError, match="kochwiki_openai_reasoning_effort"):
        Settings(_env_file=None)
