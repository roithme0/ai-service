from collections.abc import Iterator
import asyncio
import json

import httpx2
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
import pytest

from app import main
from app.agentic import lifecycle
from app.core.config import ProviderSettings
from app.agentic.config import KochwikiConversationSettings
from app.embeddings.models import DIMENSIONS, MODEL, PROFILE
from app.embeddings.service import EmbeddingService


@pytest.fixture
def provider_requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def provider_response() -> dict[str, object]:
    return {"object": "list", "model": MODEL, "data": [
        {"object": "embedding", "index": 0, "embedding": [1.0] + [0.0] * (DIMENSIONS - 1)},
    ], "usage": {"prompt_tokens": 1, "total_tokens": 1}}


@pytest.fixture
def configured_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    provider_requests: list[httpx2.Request], provider_response: dict[str, object],
) -> Iterator[None]:
    def send(request: httpx2.Request) -> httpx2.Response:
        provider_requests.append(request)
        return httpx2.Response(200, json=provider_response)

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    provider = AsyncOpenAI(api_key="test-key", http_client=http_client, max_retries=0, timeout=30.0)
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: EmbeddingService(provider))
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    yield
    assert http_client.is_closed


@pytest.fixture
def client(configured_embeddings: None) -> Iterator[TestClient]:
    with TestClient(main.app) as client:
        yield client


def test_embedding_is_independent_of_identity_and_agent_configuration(
    client: TestClient, provider_requests: list[httpx2.Request],
) -> None:
    response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup\nBrand: Farm"})
    assert response.status_code == 200
    assert response.json() == {
        "profile": PROFILE, "model": MODEL, "dimensions": DIMENSIONS,
        "vector": [1.0] + [0.0] * (DIMENSIONS - 1),
    }
    assert len(provider_requests) == 1
    assert json.loads(provider_requests[0].content) == {
        "input": "Soup\nBrand: Farm", "model": MODEL, "encoding_format": "float",
    }
    assert "X-Application-User" not in provider_requests[0].headers
    assert client.post("/api/v1/agents/kochwiki/sessions", json={}, headers={
        "X-Application-User": "test:user",
    }).status_code == 503


@pytest.mark.parametrize("body", [
    {"profile": "unknown", "input": "Soup"},
    {"profile": PROFILE, "input": ""},
    {"profile": PROFILE, "input": " \n "},
    {"profile": PROFILE, "input": 1},
    {"input": "Soup"},
    {"profile": PROFILE, "input": "Soup", "model": MODEL},
])
def test_invalid_requests_never_call_provider(
    client: TestClient, provider_requests: list[httpx2.Request], body: dict[str, object],
) -> None:
    response = client.post("/api/v1/embeddings", json=body)
    assert response.status_code == 422
    assert response.json()["kind"] == "request_validation"
    assert provider_requests == []


def test_invalid_conversation_settings_do_not_block_embeddings(
    configured_embeddings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KOCHWIKI_OPENAI_REASONING_EFFORT", "invalid")
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    with TestClient(main.app) as independent_client:
        response = independent_client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"})
        assert response.status_code == 200
        assert independent_client.post("/api/v1/agents/kochwiki/sessions", json={}, headers={
            "X-Application-User": "test:user",
        }).status_code == 503


@pytest.mark.parametrize("invalid", ["model", "count", "index", "dimension", "zero", "nonfinite"])
def test_malformed_provider_response_is_sanitized(
    client: TestClient, provider_response: dict[str, object], invalid: str,
) -> None:
    if invalid == "model":
        provider_response["model"] = "different-model"
    elif invalid == "count":
        provider_response["data"] = []
    else:
        vector: list[float | str] = [1.0] + [0.0] * (DIMENSIONS - 1)
        if invalid == "dimension":
            vector = [1.0]
        elif invalid == "zero":
            vector = [0.0] * DIMENSIONS
        elif invalid == "nonfinite":
            vector[0] = "NaN"
        provider_response["data"] = [{"index": 1 if invalid == "index" else 0, "embedding": vector}]
    response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"})
    assert response.status_code == 502
    assert response.json() == {"kind": "embedding_failed", "detail": "Embedding generation failed"}


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


@pytest.mark.parametrize("failure", ["timeout", "rate_limit"])
def test_provider_failure_is_not_retried_or_exposed(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    attempts = 0

    def send(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if failure == "timeout":
            raise httpx2.ReadTimeout("private provider detail", request=request)
        return httpx2.Response(429, json={"error": {"message": "private provider detail"}})

    provider = AsyncOpenAI(
        api_key="test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(send)),
        max_retries=0, timeout=30.0,
    )
    monkeypatch.setattr(EmbeddingService, "from_settings", lambda settings: EmbeddingService(provider))
    monkeypatch.setattr(lifecycle, "get_kochwiki_conversation_settings", lambda: KochwikiConversationSettings(_env_file=None))
    with TestClient(main.app) as client:
        response = client.post("/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"})
        assert response.status_code == 502
        assert response.json() == {"kind": "embedding_failed", "detail": "Embedding generation failed"}
    assert attempts == 1


def test_provider_configuration_preserves_timeout_and_retry_policy() -> None:
    service = EmbeddingService.from_settings(ProviderSettings(_env_file=None, openai_api_key="test-key"))
    assert service.client is not None
    assert service.client.timeout == 30.0
    assert service.client.max_retries == 0
    asyncio.run(service.close())
