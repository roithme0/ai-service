import asyncio
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai.images import ImageGenerator
from pydantic_ai.images.openai import OpenAIImageGenerationModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.capabilities.image_generation.service import ImageGenerationService
from app.core.identity import ApplicationIdentity


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("timeout", "image_generation_timeout"),
        ("empty", "image_generation_invalid_output"),
        ("base64", "image_generation_invalid_output"),
        ("format", "image_generation_invalid_output"),
    ],
)
def test_real_adapter_failure_mapping(tmp_path: Path, mode: str, expected: str) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "timeout":
            raise httpx.ReadTimeout("provider secret", request=request)
        data = {
            "empty": [],
            "base64": [{"b64_json": "invalid!"}],
            "format": [{"b64_json": "bm90IGFuIGltYWdl"}],
        }[mode]
        return httpx.Response(200, json={"created": 1, "data": data}, request=request)

    async def exercise() -> None:
        client = AsyncOpenAI(
            api_key="test",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )
        generator = ImageGenerator(
            OpenAIImageGenerationModel(
                "gpt-image-test", provider=OpenAIProvider(openai_client=client)
            ),
            instrument=False,
        )
        service = ImageGenerationService("gpt-image-test", tmp_path, generator, client)
        owner = ApplicationIdentity("issuer", "subject")
        snapshot, _ = service.submit(owner, uuid4(), "prompt")
        try:
            for _ in range(100):
                record = service.get(owner, snapshot.generation_id)
                assert record is not None
                if record.snapshot.status != "running":
                    break
                await asyncio.sleep(0.01)
            assert record.snapshot.status == "failed"
            assert record.snapshot.error.kind == expected
            assert "secret" not in record.snapshot.error.detail
            assert calls == 1
        finally:
            await service.close()

    asyncio.run(exercise())


def test_production_provider_settings_reach_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import json

    from app.capabilities.image_generation import service as service_module
    from app.capabilities.image_generation.config import ImageGenerationSettings
    from app.core.config import ProviderSettings

    requests: list[dict[str, object]] = []
    options: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "created": 1,
                "data": [
                    {"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()}
                ],
            },
            request=request,
        )

    def client_factory(**kwargs: object) -> AsyncOpenAI:
        options.append(kwargs)
        return AsyncOpenAI(
            api_key="test",
            max_retries=int(cast(int, kwargs["max_retries"])),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(service_module, "AsyncOpenAI", client_factory)

    async def exercise() -> None:
        service = ImageGenerationService.create(
            ProviderSettings(openai_api_key="test", _env_file=None),
            ImageGenerationSettings(
                image_generation_openai_model="gpt-image-2", _env_file=None
            ),
            tmp_path,
        )
        assert service.generator is not None
        assert service.generator.instrument is False
        owner = ApplicationIdentity("issuer", "subject")
        service.submit(owner, uuid4(), "  exact  ")
        try:
            await asyncio.gather(*tuple(service.tasks))
            assert len(requests) == 1
            assert {
                k: requests[0][k]
                for k in (
                    "prompt",
                    "model",
                    "n",
                    "size",
                    "quality",
                    "background",
                    "output_format",
                )
            } == {
                "prompt": "  exact  ",
                "model": "gpt-image-2",
                "n": 1,
                "size": "1024x1024",
                "quality": "medium",
                "background": "opaque",
                "output_format": "png",
            }
            assert options[0]["max_retries"] == 0
        finally:
            await service.close()

    asyncio.run(exercise())
