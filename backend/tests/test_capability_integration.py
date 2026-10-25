from collections.abc import Iterator

import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app import main
from app.capabilities.conversations import lifecycle
from app.capabilities.conversations.config import KochwikiConversationSettings
from app.capabilities.embeddings.models import DIMENSIONS, MODEL, PROFILE
from app.capabilities.embeddings.service import EmbeddingService
from app.core.config import ProviderSettings


@pytest.fixture
def configured_embeddings(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx2.Request]]:
    requests: list[httpx2.Request] = []

    def send(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={
            "object": "list", "model": MODEL,
            "data": [{"object": "embedding", "index": 0, "embedding": [1.0] + [0.0] * (DIMENSIONS - 1)}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        })

    provider = AsyncOpenAI(
        api_key="test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(send)),
        max_retries=0, timeout=30.0,
    )
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: EmbeddingService(provider))
    monkeypatch.setattr(main, "get_provider_settings", lambda: ProviderSettings(_env_file=None, openai_api_key=None))
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    yield requests
    assert provider.is_closed()


@pytest.mark.parametrize("configuration", ["missing", "invalid"])
def test_unavailable_conversations_do_not_block_embeddings(
    configured_embeddings: list[httpx2.Request], monkeypatch: pytest.MonkeyPatch, configuration: str,
) -> None:
    monkeypatch.delenv("KOCHWIKI_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("KOCHWIKI_MCP_URL", raising=False)
    if configuration == "invalid":
        monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", "invalid")
    else:
        monkeypatch.delenv("KOCHWIKI_OPENAI_REASONING_EFFORT", raising=False)

    with TestClient(main.app) as client:
        response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"})
        assert response.status_code == 200
        assert len(configured_embeddings) == 1
        assert client.post("/api/v1/agents/kochwiki/sessions", json={}, headers={
            "X-Application-User": "test:user",
        }).status_code == 503


def test_embedding_validation_uses_application_error_envelope(
    configured_embeddings: list[httpx2.Request],
) -> None:
    with TestClient(main.app) as client:
        response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": ""})
        assert response.status_code == 422
        assert response.json()["kind"] == "request_validation"
        assert configured_embeddings == []


def test_missing_provider_does_not_disable_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    monkeypatch.setattr(main, "get_provider_settings", lambda: ProviderSettings(_env_file=None, openai_api_key=None))
    with TestClient(main.app) as client:
        response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"})
        assert response.status_code == 503
        assert response.json()["kind"] == "embedding_unavailable"
        assert client.post("/api/v1/agents/demo/sessions", json={}, headers={
            "X-Application-User": "test:user",
        }).status_code == 201
