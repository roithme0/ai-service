from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
import asyncio
import json

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
import pytest

from app.core.config import ProviderSettings
from app.capabilities.embeddings.http import router
from app.capabilities.embeddings.lifecycle import embedding_service
from app.capabilities.embeddings.config import DIMENSIONS, MODEL, PROFILE
from app.capabilities.embeddings.service import EmbeddingService


@pytest.fixture
def provider_requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def provider_response() -> dict[str, object]:
    return {
        "object": "list",
        "model": MODEL,
        "data": [
            {
                "object": "embedding",
                "index": 0,
                "embedding": [1.0] + [0.0] * (DIMENSIONS - 1),
            },
        ],
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }


@pytest.fixture
def configured_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    provider_requests: list[httpx2.Request],
    provider_response: dict[str, object],
) -> Iterator[None]:
    def send(request: httpx2.Request) -> httpx2.Response:
        provider_requests.append(request)
        return httpx2.Response(200, json=provider_response)

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(send))
    provider = AsyncOpenAI(
        api_key="test-key", http_client=http_client, max_retries=0, timeout=30.0
    )
    monkeypatch.setattr(
        EmbeddingService, "from_settings", lambda settings: EmbeddingService(provider)
    )
    yield
    assert http_client.is_closed


@pytest.fixture
def application() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = ProviderSettings(_env_file=None, openai_api_key=None)
        async with embedding_service(settings) as service:
            app.state.embedding_service = service
            yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return app


@pytest.fixture
def client(application: FastAPI, configured_embeddings: None) -> Iterator[TestClient]:
    with TestClient(application) as client:
        yield client


def test_embedding_request_and_response_are_independent_of_identity(
    client: TestClient,
    provider_requests: list[httpx2.Request],
) -> None:
    response = client.post(
        "/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup\nBrand: Farm"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "profile": PROFILE,
        "model": MODEL,
        "dimensions": DIMENSIONS,
        "vector": [1.0] + [0.0] * (DIMENSIONS - 1),
    }
    assert len(provider_requests) == 1
    assert json.loads(provider_requests[0].content) == {
        "input": "Soup\nBrand: Farm",
        "model": MODEL,
        "encoding_format": "float",
    }
    assert "X-Application-User" not in provider_requests[0].headers


@pytest.mark.parametrize(
    "body",
    [
        {"profile": "unknown", "input": "Soup"},
        {"profile": PROFILE, "input": ""},
        {"profile": PROFILE, "input": " \n "},
        {"profile": PROFILE, "input": 1},
        {"input": "Soup"},
        {"profile": PROFILE, "input": "Soup", "model": MODEL},
    ],
)
def test_invalid_requests_never_call_provider(
    client: TestClient,
    provider_requests: list[httpx2.Request],
    body: dict[str, object],
) -> None:
    response = client.post("/api/v1/embeddings", json=body)
    assert response.status_code == 422
    assert provider_requests == []


@pytest.mark.parametrize(
    "invalid", ["model", "count", "index", "dimension", "zero", "nonfinite"]
)
def test_malformed_provider_response_is_sanitized(
    client: TestClient,
    provider_response: dict[str, object],
    invalid: str,
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
        provider_response["data"] = [
            {"index": 1 if invalid == "index" else 0, "embedding": vector}
        ]
    response = client.post(
        "/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"}
    )
    assert response.status_code == 502
    assert response.json() == {
        "kind": "embedding_failed",
        "detail": "Embedding generation failed",
    }


def test_missing_provider_returns_unavailable(application: FastAPI) -> None:
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"}
        )
        assert response.status_code == 503
        assert response.json() == {
            "kind": "embedding_unavailable",
            "detail": "Embedding provider is not configured",
        }


@pytest.mark.parametrize("failure", ["timeout", "rate_limit"])
def test_provider_failure_is_not_retried_or_exposed(
    application: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    attempts = 0

    def send(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if failure == "timeout":
            raise httpx2.ReadTimeout("private provider detail", request=request)
        return httpx2.Response(
            429, json={"error": {"message": "private provider detail"}}
        )

    provider = AsyncOpenAI(
        api_key="test-key",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(send)),
        max_retries=0,
        timeout=30.0,
    )
    monkeypatch.setattr(
        EmbeddingService, "from_settings", lambda settings: EmbeddingService(provider)
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/embeddings", json={"profile": PROFILE, "input": "Soup"}
        )
        assert response.status_code == 502
        assert response.json() == {
            "kind": "embedding_failed",
            "detail": "Embedding generation failed",
        }
    assert attempts == 1
    assert provider.is_closed()


def test_provider_configuration_preserves_timeout_and_retry_policy() -> None:
    service = EmbeddingService.from_settings(
        ProviderSettings(_env_file=None, openai_api_key="test-key")
    )
    assert service.client is not None
    assert service.client.timeout == 30.0
    assert service.client.max_retries == 0
    asyncio.run(service.close())
