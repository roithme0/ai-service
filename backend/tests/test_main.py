from fastapi.testclient import TestClient

from app.agents.wiring import get_configured_agents
from app.main import app

client = TestClient(app)


def test_hello_world() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_lifespan_initializes_and_releases_configured_agents() -> None:
    get_configured_agents.cache_clear()

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert get_configured_agents.cache_info().currsize == 1

    assert get_configured_agents.cache_info().currsize == 0
