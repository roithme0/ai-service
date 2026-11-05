from collections.abc import Iterator

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.capabilities.transcriptions.http import MAX_AUDIO_BYTES, router
from app.capabilities.transcriptions.service import TranscriptionService


@pytest.fixture
def provider_requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def client(provider_requests: list[httpx2.Request]) -> Iterator[TestClient]:
    def send(request: httpx2.Request) -> httpx2.Response:
        provider_requests.append(request)
        return httpx2.Response(200, json={"text": "  Hallo 世界  "})

    provider = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    service = TranscriptionService("test-key", "gpt-transcribe", http_client=provider)
    app = FastAPI()
    app.state.transcription_service = service
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_transcription_upload(
    client: TestClient, provider_requests: list[httpx2.Request]
) -> None:
    response = client.post(
        "/api/v1/transcriptions",
        content=b"audio-data",
        headers={"content-type": "audio/webm;codecs=opus"},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "  Hallo 世界  "}
    assert len(provider_requests) == 1
    body = provider_requests[0].content
    assert b"audio-data" in body
    assert b'filename="recording.webm"' in body
    assert b"audio/webm;codecs=opus" in body
    assert b"gpt-transcribe" in body
    assert b'name="language"' not in body
    assert b'name="prompt"' not in body


@pytest.mark.parametrize(
    "content,media,status,kind",
    [
        (b"x", "application/json", 415, "unsupported_audio"),
        (b"", "audio/ogg", 422, "invalid_audio"),
    ],
)
def test_rejected_audio_does_not_reach_provider(
    client: TestClient,
    provider_requests: list[httpx2.Request],
    content: bytes,
    media: str,
    status: int,
    kind: str,
) -> None:
    response = client.post(
        "/api/v1/transcriptions", content=content, headers={"content-type": media}
    )
    assert response.status_code == status
    assert response.json()["kind"] == kind
    assert not provider_requests


def test_oversized_audio(
    client: TestClient, provider_requests: list[httpx2.Request]
) -> None:
    response = client.post(
        "/api/v1/transcriptions",
        content=b"x" * (MAX_AUDIO_BYTES + 1),
        headers={"content-type": "audio/ogg"},
    )
    assert response.status_code == 413
    assert response.json()["kind"] == "audio_too_large"
    assert not provider_requests


def test_generated_contract_matches_transcription_router() -> None:
    import json
    from pathlib import Path

    app = FastAPI()
    app.include_router(router)
    contract = (
        Path(__file__).resolve().parents[4]
        / "frontend/projects/chat-ui/transcription/src/generated/openapi.json"
    )
    assert json.loads(contract.read_text(encoding="utf-8")) == app.openapi()
