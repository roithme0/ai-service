import asyncio
from collections.abc import Iterator

import httpx2
import pytest
from fastapi import FastAPI

from app.main import create_app


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def mcp_http_client(app: FastAPI) -> Iterator[httpx2.AsyncClient]:
    client = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app))
    try:
        yield client
    finally:
        asyncio.run(client.aclose())
