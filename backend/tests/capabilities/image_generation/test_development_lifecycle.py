"""Configuration and resource lifecycle regression coverage."""

from pathlib import Path
import subprocess
import sys

import pytest

from app.capabilities.image_generation.config import ImageGenerationSettings
from app.capabilities.image_generation.lifecycle import image_generation_service
from app.capabilities.image_generation.service import ImageGenerationService
from app.core.config import ProviderSettings


def test_close_settles_already_finished_cleanup_without_callback() -> None:
    program = """
import asyncio
from app.capabilities.image_generation.service import ImageGenerationService

async def main():
    service = ImageGenerationService(None, None, None, None)
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    service.cleanups.add(task)
    await service.close()

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_blank_settings_disable_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGE_GENERATION_OPENAI_MODEL", " ")
    monkeypatch.setenv("IMAGE_GENERATION_STORAGE_ROOT", " ")
    settings = ImageGenerationSettings(_env_file=None)
    assert settings.image_generation_openai_model is None
    assert settings.image_generation_storage_root is None
    service = ImageGenerationService.create(
        ProviderSettings(_env_file=None), settings, None
    )
    assert service.generator is None
    assert service.client is None


@pytest.mark.anyio
async def test_lifecycle_closes_provider_after_later_startup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IMAGE_GENERATION_OPENAI_MODEL", "gpt-image-2")
    monkeypatch.setenv("IMAGE_GENERATION_STORAGE_ROOT", str(tmp_path))
    provider = ProviderSettings(openai_api_key="test", _env_file=None)
    service: ImageGenerationService | None = None
    with pytest.raises(RuntimeError, match="later startup"):
        async with image_generation_service(provider) as service:
            assert service.client is not None
            assert service.generator is not None
            raise RuntimeError("later startup")
    assert service is not None
    assert service.closing
    assert service.client is not None
    assert service.client.is_closed()


@pytest.mark.anyio
async def test_relative_storage_fails_even_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_GENERATION_STORAGE_ROOT", "relative-image-storage")
    monkeypatch.setenv("IMAGE_GENERATION_OPENAI_MODEL", "")
    with pytest.raises(ValueError, match="absolute"):
        async with image_generation_service(ProviderSettings(_env_file=None)):
            pytest.fail("relative storage must fail startup")
