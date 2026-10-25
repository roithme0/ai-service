from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import ProviderSettings
from app.capabilities.conversations.config import KochwikiConversationSettings


def clear_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KOCHWIKI_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("KOCHWIKI_OPENAI_REASONING_EFFORT", raising=False)


def test_settings_are_optional_when_provider_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_provider_environment(monkeypatch)
    provider = ProviderSettings(_env_file=None)
    settings = KochwikiConversationSettings(_env_file=None)

    assert provider.openai_api_key is None
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

    provider = ProviderSettings(_env_file=env_file)
    settings = KochwikiConversationSettings(_env_file=env_file)

    assert provider.openai_api_key is not None
    assert provider.openai_api_key.get_secret_value() == "secret-key"
    assert settings.kochwiki_openai_model == "gpt-test"
    assert settings.kochwiki_openai_reasoning_effort == "high"


def test_blank_settings_are_treated_as_unset() -> None:
    provider = ProviderSettings(_env_file=None, openai_api_key="   ")
    settings = KochwikiConversationSettings(
        _env_file=None,
        kochwiki_openai_model=" ",
        kochwiki_openai_reasoning_effort=" ",
    )

    assert provider.openai_api_key is None
    assert settings.kochwiki_openai_model is None
    assert settings.kochwiki_openai_reasoning_effort is None


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max", "", "   "])
def test_reasoning_effort_from_process_environment(
    monkeypatch: pytest.MonkeyPatch, effort: str,
) -> None:
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", effort)
    settings = KochwikiConversationSettings(_env_file=None)

    assert settings.kochwiki_openai_reasoning_effort == (effort.strip() or None)


@pytest.mark.parametrize("effort", ["invalid", "HIGH", "default"])
def test_unknown_reasoning_effort_is_rejected(
    monkeypatch: pytest.MonkeyPatch, effort: str,
) -> None:
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", effort)

    with pytest.raises(ValidationError, match="kochwiki_openai_reasoning_effort"):
        KochwikiConversationSettings(_env_file=None)


def test_provider_settings_ignore_invalid_conversation_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", " test-key ")
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", "invalid")

    provider = ProviderSettings(_env_file=None)
    assert provider.openai_api_key is not None
    assert provider.openai_api_key.get_secret_value() == "test-key"
    with pytest.raises(ValidationError, match="kochwiki_openai_reasoning_effort"):
        KochwikiConversationSettings(_env_file=None)
