from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.agents.http import create_session_router
from app.agents.models.http_responses import (
    AcceptedTurnResponse,
    SessionCreationResponse,
    SessionSnapshotResponse,
    UserMessageResponse,
)
from app.agents.protocols.http import ConversationTransport


class CustomTransport:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def create(self, value: object, owner: str) -> SessionCreationResponse:
        assert value == {"custom": True}
        assert owner == "test:user"
        return SessionCreationResponse(
            session_id=self.session_id, expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )

    def read(self, session_id: str, owner: str) -> SessionSnapshotResponse:
        raise AssertionError("Unexpected read")

    def append(self, session_id: str, text: str, owner: str) -> UserMessageResponse:
        raise AssertionError("Unexpected append")

    def turn(self, session_id: str, owner: str) -> AcceptedTurnResponse:
        raise AssertionError("Unexpected turn")

    def observe(self, session_id: str, turn_id: str, owner: str) -> StreamingResponse:
        raise AssertionError("Unexpected observation")


def test_router_resolves_supplied_provider_per_request_and_supports_overrides() -> None:
    calls = 0
    registry: dict[str, ConversationTransport | None] = {"custom": CustomTransport("first")}

    def provider() -> dict[str, ConversationTransport | None]:
        nonlocal calls
        calls += 1
        return registry

    app = FastAPI()
    app.include_router(create_session_router(provider, ("custom",)))
    assert calls == 0
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/agents/{configuration}/sessions"]["post"]
    assert operation["parameters"][0]["schema"]["enum"] == ["custom"]

    with TestClient(app, headers={"X-Application-User": "test:user"}) as client:
        def create() -> str:
            response = client.post("/api/v1/agents/custom/sessions", json={"input": {"custom": True}})
            assert response.status_code == 201
            session_id = response.json()["session_id"]
            assert isinstance(session_id, str)
            return session_id

        assert create() == "first"
        registry["custom"] = CustomTransport("second")
        assert create() == "second"
        assert calls == 2

        def override() -> dict[str, ConversationTransport | None]:
            return {"custom": CustomTransport("override")}

        app.dependency_overrides[provider] = override
        assert create() == "override"
        assert calls == 2
