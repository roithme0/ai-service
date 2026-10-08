"""HTTP transport contract consumed by the session router."""

from typing import Protocol

from fastapi.responses import JSONResponse, StreamingResponse

from app.sessions.models.http import (
    AcceptedTurnResponse,
    SessionCreationResponse,
    SessionSnapshotResponse,
    UserMessageResponse,
)


class ConversationTransport(Protocol):
    def create(
        self, value: object, owner: str
    ) -> SessionCreationResponse | JSONResponse: ...
    def read(
        self, session_id: str, owner: str
    ) -> SessionSnapshotResponse | JSONResponse: ...
    def append(
        self, session_id: str, text: str, owner: str
    ) -> UserMessageResponse | JSONResponse: ...
    def turn(
        self, session_id: str, owner: str
    ) -> AcceptedTurnResponse | JSONResponse: ...
    def observe(
        self, session_id: str, turn_id: str, owner: str
    ) -> StreamingResponse | JSONResponse: ...


