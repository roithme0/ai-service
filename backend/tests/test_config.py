from pathlib import Path

import pytest

from app.core.config import Settings


def clear_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RECIPE_IMPROVEMENT_OPENAI_MODEL", raising=False)


def test_settings_are_optional_when_provider_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_provider_environment(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.openai_api_key is None
    assert settings.recipe_improvement_openai_model is None


def test_settings_load_and_normalize_an_explicit_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_provider_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_API_KEY=secret-key\n"
        "RECIPE_IMPROVEMENT_OPENAI_MODEL=  gpt-test  \n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "secret-key"
    assert settings.recipe_improvement_openai_model == "gpt-test"


def test_blank_settings_are_treated_as_unset() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="   ",
        recipe_improvement_openai_model=" ",
    )

    assert settings.openai_api_key is None
    assert settings.recipe_improvement_openai_model is None
