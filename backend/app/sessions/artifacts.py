"""Typed artifact preparation and registration over the conversation store."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

from app.sessions.conversation import (
    ConversationSessionStore,
    ConversationStageAccepted,
    ConversationStageRejected,
    ConversationTurnView,
)

ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")
RejectionT = TypeVar("RejectionT")


@dataclass(frozen=True)
class ArtifactPrepared(Generic[ArtifactT]):
    payload: ArtifactT
    referenced_artifact_id: str | None = None


@dataclass(frozen=True)
class ArtifactPreparationRejected(Generic[RejectionT]):
    detail: RejectionT
    stage: str = "validation"


class ArtifactHandler(Protocol[ContextT, ArtifactT, RejectionT]):
    async def prepare(
        self, view: ConversationTurnView[ContextT, ArtifactT], candidate: object
    ) -> ArtifactPrepared[ArtifactT] | ArtifactPreparationRejected[RejectionT]: ...


@dataclass(frozen=True)
class ArtifactTypeUnsupported:
    kind: Literal["unsupported_type"] = "unsupported_type"


class ArtifactRegistry(Generic[ContextT, ArtifactT, RejectionT]):
    def __init__(
        self, handlers: Iterable[tuple[str, ArtifactHandler[ContextT, ArtifactT, RejectionT]]]
    ) -> None:
        self._handlers: dict[str, ArtifactHandler[ContextT, ArtifactT, RejectionT]] = {}
        for artifact_type, handler in handlers:
            if artifact_type in self._handlers:
                raise ValueError(f"duplicate artifact handler: {artifact_type}")
            self._handlers[artifact_type] = handler

    async def register(
        self, store: ConversationSessionStore[ContextT, ArtifactT],
        session_id: str, turn_id: str, artifact_type: str, candidate: object,
    ) -> (
        ConversationStageAccepted[ArtifactT]
        | ConversationStageRejected
        | ArtifactPreparationRejected[RejectionT]
        | ArtifactTypeUnsupported
    ):
        handler = self._handlers.get(artifact_type)
        if handler is None:
            return ArtifactTypeUnsupported()
        view = store.inspect_turn(session_id, turn_id)
        if isinstance(view, ConversationStageRejected):
            return view
        prepared = await handler.prepare(view, candidate)
        if isinstance(prepared, ArtifactPreparationRejected):
            return prepared
        return store.stage_artifact(
            session_id, turn_id, artifact_type, prepared.payload, prepared.referenced_artifact_id
        )
