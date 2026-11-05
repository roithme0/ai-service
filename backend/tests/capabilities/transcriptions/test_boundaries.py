from collections.abc import Iterator

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.capabilities.transcriptions.http import MAX_AUDIO_BYTES, router
from app.capabilities.transcriptions.service import TranscriptionService
from test_transcriptions import client, provider_requests


@pytest.mark.parametrize(
    "media,suffix",
    [
        ("AuDiO/WeBm; codecs=opus", ".webm"),
        ("audio/mp4; codecs=mp4a.40.2", ".mp4"),
        ("audio/ogg; codecs=opus", ".ogg"),
        ("audio/x-m4a", ".m4a"),
        ("audio/x-wav", ".wav"),
        ("audio/mpga", ".mpga"),
        ("audio/x-flac", ".flac"),
    ],
)
def test_supported_media_types_preserve_metadata(
    client: TestClient, provider_requests: list[httpx2.Request], media: str, suffix: str
) -> None:
    response = client.post(
        "/api/v1/transcriptions", content=b"audio", headers={"content-type": media}
    )
    assert response.status_code == 200
    assert f'filename="recording{suffix}"'.encode() in provider_requests[0].content
    assert media.encode() in provider_requests[0].content


def test_missing_content_type_is_rejected(
    client: TestClient, provider_requests: list[httpx2.Request]
) -> None:
    response = client.post("/api/v1/transcriptions", content=b"audio")
    assert response.status_code == 415
    assert response.json() == {
        "kind": "unsupported_audio",
        "detail": "Unsupported audio content type",
    }
    assert not provider_requests


@pytest.mark.parametrize(
    "size,status", [(MAX_AUDIO_BYTES, 200), (MAX_AUDIO_BYTES + 1, 413)]
)
def test_streamed_upload_size_boundary(
    client: TestClient, provider_requests: list[httpx2.Request], size: int, status: int
) -> None:
    def chunks() -> Iterator[bytes]:
        remaining = size
        while remaining:
            chunk_size = min(1_000_000, remaining)
            yield b"x" * chunk_size
            remaining -= chunk_size

    response = client.post(
        "/api/v1/transcriptions",
        content=chunks(),
        headers={"content-type": "audio/ogg"},
    )
    assert response.status_code == status
    assert len(provider_requests) == (1 if status == 200 else 0)


@pytest.mark.parametrize(
    "provider_status,body,expected_status,kind",
    [
        (
            429,
            {"error": {"message": "secret payload"}},
            503,
            "transcription_unavailable",
        ),
        (
            503,
            {"error": {"code": "server_overloaded", "message": "secret payload"}},
            503,
            "transcription_unavailable",
        ),
        (401, {"error": {"message": "secret payload"}}, 502, "transcription_failed"),
        (
            400,
            {"error": {"code": "invalid_audio", "message": "secret payload"}},
            422,
            "invalid_audio",
        ),
        (400, {"error": {"message": "secret payload"}}, 502, "transcription_failed"),
        (200, {"text": 123, "secret": "secret payload"}, 502, "transcription_failed"),
        (200, {}, 502, "transcription_failed"),
    ],
)
def test_provider_failures_are_safe_and_not_retried(
    provider_status: int,
    body: dict[str, object],
    expected_status: int,
    kind: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx2.Request] = []

    def send(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(provider_status, json=body)

    provider = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    app = FastAPI()
    app.state.transcription_service = TranscriptionService(
        "test-key", "gpt-transcribe", http_client=provider
    )
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/transcriptions",
            content=b"private audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == expected_status
    assert response.json()["kind"] == kind
    assert "secret payload" not in response.text
    assert "secret payload" not in caplog.text
    assert "private audio" not in caplog.text
    assert len(requests) == 1


def test_empty_transcript_is_preserved() -> None:
    provider = httpx2.AsyncClient(
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, json={"text": ""})
        )
    )
    app = FastAPI()
    app.state.transcription_service = TranscriptionService(
        "test-key", "gpt-transcribe", http_client=provider
    )
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == 200
    assert response.json() == {"text": ""}


def test_missing_key_is_unavailable() -> None:
    app = FastAPI()
    app.state.transcription_service = TranscriptionService(None, "gpt-transcribe")
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == 503
    assert response.json()["kind"] == "transcription_unavailable"


def test_network_failure_maps_to_safe_failure() -> None:
    def send(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("private provider detail", request=request)

    provider = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    app = FastAPI()
    app.state.transcription_service = TranscriptionService(
        "test-key", "gpt-transcribe", http_client=provider
    )
    app.include_router(router)
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == 502
    assert response.json() == {
        "kind": "transcription_failed",
        "detail": "Transcription failed",
    }


def test_configured_model_is_used() -> None:
    requests: list[httpx2.Request] = []

    def send(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"text": "ok"})

    provider = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    app = FastAPI()
    app.state.transcription_service = TranscriptionService(
        "test-key", "custom-model", http_client=provider
    )
    app.include_router(router)
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == 200
    assert b"custom-model" in requests[0].content


def test_provider_deadline_cancels_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def run() -> None:
        cancelled = asyncio.Event()
        original_timeout = asyncio.timeout

        async def send(request: httpx2.Request) -> httpx2.Response:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            return httpx2.Response(200, json={"text": "late"})

        provider = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
        service = TranscriptionService(
            "test-key", "gpt-transcribe", http_client=provider
        )
        monkeypatch.setattr(asyncio, "timeout", lambda seconds: original_timeout(0.01))
        with pytest.raises(TimeoutError):
            await service.transcribe(b"audio", "audio/ogg", ".ogg")
        assert cancelled.is_set()
        await service.close()

    asyncio.run(run())


def test_lifecycle_closes_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from app.capabilities.transcriptions.lifecycle import transcription_service
    from app.core.config import ProviderSettings

    async def run() -> None:
        provider = httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(200, json={"text": "ok"})
            )
        )
        service = TranscriptionService(
            "test-key", "gpt-transcribe", http_client=provider
        )
        monkeypatch.setattr(
            TranscriptionService,
            "from_settings",
            lambda provider_settings, settings: service,
        )
        async with transcription_service(
            ProviderSettings(_env_file=None, openai_api_key=None)
        ) as resource:
            assert resource is service
            assert not provider.is_closed
        assert provider.is_closed

    asyncio.run(run())


def test_application_starts_without_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import lifespan
    from app.core.config import ProviderSettings
    from app.main import app

    monkeypatch.setattr(
        lifespan,
        "get_provider_settings",
        lambda: ProviderSettings(_env_file=None, openai_api_key=None),
    )
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
        assert response.status_code == 503
        assert app.state.agent_runners["visual-demo"] is not None


def test_provider_deadline_maps_to_safe_http_timeout() -> None:
    from typing import cast

    class Provider:
        async def transcribe(self, audio: bytes, media_type: str, suffix: str) -> str:
            raise TimeoutError()

    app = FastAPI()
    app.state.transcription_service = cast(TranscriptionService, Provider())
    app.include_router(router)
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/transcriptions",
            content=b"audio",
            headers={"content-type": "audio/ogg"},
        )
    assert response.status_code == 504
    assert response.json() == {
        "kind": "transcription_timeout",
        "detail": "Transcription timed out",
    }


def test_default_model_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.capabilities.transcriptions.config import TranscriptionSettings

    monkeypatch.delenv("TRANSCRIPTION_OPENAI_MODEL", raising=False)
    assert (
        TranscriptionSettings(_env_file=None).transcription_openai_model
        == "gpt-transcribe"
    )
