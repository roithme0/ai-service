"""Process-local session, turn, and staged-artifact lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Generic, Literal, TypeVar
from uuid import uuid4

from app.sessions.text_sessions import (
    EphemeralTextSessionStore,
    MAX_MESSAGE_COUNT,
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionAppendOutcome,
    TextSessionAppendUnknown,
    TextSessionCreation,
    TextSessionReadActive,
    TextSessionReadExpired,
    TextSessionReadUnknown,
    TextSessionSnapshot,
)


ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")
TurnKind = Literal["completed", "generation_failed", "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]


@dataclass(frozen=True)
class StagedArtifact(Generic[ArtifactT]):
    artifact_id: str
    type: str
    created_at: datetime
    order: int
    turn_id: str
    payload: ArtifactT


@dataclass(frozen=True)
class ConversationSessionSettings:
    max_artifacts: int

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError("max_artifacts must be positive")


@dataclass(frozen=True)
class ConversationTurnResult(Generic[ArtifactT]):
    kind: TurnKind
    turn_id: str
    text: str | None
    artifacts: tuple[StagedArtifact[ArtifactT], ...]


@dataclass(frozen=True)
class ConversationTurnReservation(Generic[ContextT, ArtifactT]):
    turn_id: str
    snapshot: TextSessionSnapshot[ContextT]
    previous_artifacts: tuple[StagedArtifact[ArtifactT], ...]


@dataclass(frozen=True)
class ConversationSnapshot(Generic[ContextT, ArtifactT]):
    session: TextSessionSnapshot[ContextT]
    artifacts: tuple[StagedArtifact[ArtifactT], ...]
    terminal_turn_id: str | None
    terminal_turn_kind: TurnKind | None


@dataclass(frozen=True)
class ConversationReadActive(Generic[ContextT, ArtifactT]):
    kind: Literal["active"]
    snapshot: ConversationSnapshot[ContextT, ArtifactT]


@dataclass(frozen=True)
class ConversationMessageBusy:
    session_id: str
    kind: Literal["busy"] = "busy"


@dataclass(frozen=True)
class ConversationStageAccepted(Generic[ArtifactT]):
    kind: Literal["accepted"]
    artifact: StagedArtifact[ArtifactT]


@dataclass(frozen=True)
class ConversationStageRejected:
    kind: Literal["unknown", "expired", "limit_reached", "missing_reference"]


@dataclass(frozen=True)
class ConversationTurnView(Generic[ContextT, ArtifactT]):
    snapshot: TextSessionSnapshot[ContextT]
    artifacts: tuple[StagedArtifact[ArtifactT], ...]
    max_artifacts: int


@dataclass(frozen=True)
class _TerminalTurn(Generic[ArtifactT]):
    revision: int
    result: ConversationTurnResult[ArtifactT]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationSessionStore(Generic[ContextT, ArtifactT]):
    def __init__(
        self,
        lifetime: timedelta,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._core = EphemeralTextSessionStore[ContextT](lifetime=lifetime, clock=clock)
        self._clock = clock
        self._lock = RLock()
        self._settings: dict[str, ConversationSessionSettings] = {}
        self._artifacts: dict[str, tuple[StagedArtifact[ArtifactT], ...]] = {}
        self._active_turns: dict[str, str] = {}
        self._terminal_turns: dict[str, _TerminalTurn[ArtifactT]] = {}

    def create(self, context: ContextT, settings: ConversationSessionSettings) -> TextSessionCreation:
        with self._lock:
            tracked = self._settings.keys() | self._artifacts.keys() | self._active_turns.keys() | self._terminal_turns.keys()
            for session_id in tuple(tracked):
                if not isinstance(self._core.read(session_id), TextSessionReadActive):
                    self._discard(session_id)
            created = self._core.create(context)
            self._settings[created.session_id] = settings
            return created

    def read(self, session_id: str) -> ConversationReadActive[ContextT, ArtifactT] | TextSessionReadExpired | TextSessionReadUnknown:
        with self._lock:
            outcome = self._core.read(session_id)
            if not isinstance(outcome, TextSessionReadActive):
                self._discard(session_id)
                return outcome
            active_turn_id = self._active_turns.get(session_id)
            terminal = self._terminal_turns.get(session_id)
            return ConversationReadActive(
                kind="active",
                snapshot=ConversationSnapshot(
                    session=outcome.session,
                    artifacts=tuple(deepcopy(artifact) for artifact in self._artifacts.get(session_id, ()) if artifact.turn_id != active_turn_id),
                    terminal_turn_id=terminal.result.turn_id if terminal else None,
                    terminal_turn_kind=terminal.result.kind if terminal else None,
                ),
            )

    def append_user_message(self, session_id: str, text: object) -> TextSessionAppendOutcome | ConversationMessageBusy:
        with self._lock:
            read = self._core.read(session_id)
            if isinstance(read, TextSessionReadExpired):
                self._discard(session_id)
                return TextSessionAppendExpired(kind="expired", session_id=session_id, expires_at=read.expires_at)
            if isinstance(read, TextSessionReadUnknown):
                self._discard(session_id)
                return TextSessionAppendUnknown(kind="unknown", session_id=session_id)
            if session_id in self._active_turns:
                return ConversationMessageBusy(session_id=session_id)
            appended = self._core.append_with_max_message_count(session_id, "user", text, MAX_MESSAGE_COUNT - 1)
            if isinstance(appended, TextSessionAppendAccepted):
                self._terminal_turns.pop(session_id, None)
            return appended

    def reserve_turn(self, session_id: str) -> ConversationTurnReservation[ContextT, ArtifactT] | ConversationTurnResult[ArtifactT]:
        with self._lock:
            read = self._core.read(session_id)
            if not isinstance(read, TextSessionReadActive):
                self._discard(session_id)
                return ConversationTurnResult(read.kind, "", None, ())
            if session_id in self._active_turns:
                return ConversationTurnResult("busy", "", None, ())
            terminal = self._terminal_turns.get(session_id)
            if terminal and terminal.revision == read.session.revision and terminal.result.kind == "generation_failed":
                return terminal.result
            if not read.session.messages or read.session.messages[-1].role != "user":
                return ConversationTurnResult("not_ready", "", None, ())
            if len(read.session.messages) >= MAX_MESSAGE_COUNT:
                return ConversationTurnResult("limit_reached", "", None, ())
            turn_id = str(uuid4())
            self._active_turns[session_id] = turn_id
            return ConversationTurnReservation(turn_id, read.session, tuple(deepcopy(self._artifacts.get(session_id, ()))))

    def inspect_turn(self, session_id: str, turn_id: str) -> ConversationTurnView[ContextT, ArtifactT] | ConversationStageRejected:
        with self._lock:
            read = self._core.read(session_id)
            if not isinstance(read, TextSessionReadActive):
                self._discard(session_id)
                return ConversationStageRejected(read.kind)
            if self._active_turns.get(session_id) != turn_id:
                return ConversationStageRejected("unknown")
            return ConversationTurnView(
                read.session, tuple(deepcopy(self._artifacts.get(session_id, ()))),
                self._settings[session_id].max_artifacts,
            )

    def stage_artifact(
        self, session_id: str, turn_id: str, artifact_type: str, payload: ArtifactT,
        referenced_artifact_id: str | None = None,
    ) -> ConversationStageAccepted[ArtifactT] | ConversationStageRejected:
        with self._lock:
            view = self.inspect_turn(session_id, turn_id)
            if isinstance(view, ConversationStageRejected):
                return view
            artifacts = self._artifacts.get(session_id, ())
            if referenced_artifact_id is not None and not any(
                a.artifact_id == referenced_artifact_id for a in artifacts
            ):
                return ConversationStageRejected("missing_reference")
            if len(artifacts) >= view.max_artifacts:
                return ConversationStageRejected("limit_reached")
            artifact = StagedArtifact(
                artifact_id=str(uuid4()),
                type=artifact_type,
                created_at=self._clock().astimezone(UTC),
                order=len(artifacts) + 1,
                turn_id=turn_id,
                payload=deepcopy(payload),
            )
            self._artifacts[session_id] = (*artifacts, artifact)
            return ConversationStageAccepted("accepted", deepcopy(artifact))

    def complete_turn(
        self, session_id: str, reservation: ConversationTurnReservation[ContextT, ArtifactT],
        kind: Literal["completed", "generation_failed"], text: str | None,
    ) -> ConversationTurnResult[ArtifactT]:
        with self._lock:
            current = self._core.read(session_id)
            if not isinstance(current, TextSessionReadActive):
                self._discard(session_id)
                return ConversationTurnResult(current.kind, reservation.turn_id, None, ())
            if self._active_turns.get(session_id) != reservation.turn_id:
                return ConversationTurnResult("conflict", reservation.turn_id, None, ())
            if current.session.revision != reservation.snapshot.revision:
                final = ConversationTurnResult[ArtifactT]("conflict", reservation.turn_id, None, ())
            elif kind == "completed" and text is not None:
                appended = self._core.append_if_revision(session_id, reservation.snapshot.revision, "assistant", text, turn_id=reservation.turn_id)
                if isinstance(appended, TextSessionAppendAccepted):
                    artifacts = tuple(deepcopy(a) for a in self._artifacts.get(session_id, ()) if a.turn_id == reservation.turn_id)
                    final = ConversationTurnResult("completed", reservation.turn_id, text, artifacts)
                else:
                    final = ConversationTurnResult("conflict", reservation.turn_id, None, ())
            else:
                final = ConversationTurnResult("generation_failed", reservation.turn_id, None, ())
            return self._finish_turn(session_id, reservation, final)

    def fail_turn(
        self, session_id: str, reservation: ConversationTurnReservation[ContextT, ArtifactT]
    ) -> ConversationTurnResult[ArtifactT]:
        with self._lock:
            current = self._core.read(session_id)
            if not isinstance(current, TextSessionReadActive):
                self._discard(session_id)
                return ConversationTurnResult(current.kind, reservation.turn_id, None, ())
            if self._active_turns.get(session_id) != reservation.turn_id:
                return ConversationTurnResult("conflict", reservation.turn_id, None, ())
            return self._finish_turn(session_id, reservation, ConversationTurnResult("generation_failed", reservation.turn_id, None, ()))

    def _finish_turn(
        self, session_id: str, reservation: ConversationTurnReservation[ContextT, ArtifactT],
        final: ConversationTurnResult[ArtifactT],
    ) -> ConversationTurnResult[ArtifactT]:
        if final.kind in ("expired", "unknown"):
            self._discard(session_id)
        else:
            if final.kind != "completed":
                retained = tuple(a for a in self._artifacts.get(session_id, ()) if a.turn_id != reservation.turn_id)
                if retained:
                    self._artifacts[session_id] = retained
                else:
                    self._artifacts.pop(session_id, None)
            revision = reservation.snapshot.revision + (1 if final.kind == "completed" else 0)
            self._terminal_turns[session_id] = _TerminalTurn(revision, final)
            self._active_turns.pop(session_id, None)
        return final

    def _discard(self, session_id: str) -> None:
        self._settings.pop(session_id, None)
        self._artifacts.pop(session_id, None)
        self._active_turns.pop(session_id, None)
        self._terminal_turns.pop(session_id, None)
