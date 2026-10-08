"""Process-local conversation lifecycle backed by ordered history."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Generic, TypeVar, cast
from uuid import uuid4

from app.sessions.models.history import ArtifactRecord, CallRecord, ExecutionReportRecord, ExecutionStartedRecord, HostedToolRecord, ContinuationRecord, HistoryRecord, MessageRecord, TerminalRecord, ToolResultRecord, TurnActivityRecord
from app.sessions.history import completed_text_messages
from app.sessions.models.artifacts import (
    ArtifactCandidate,
    ArtifactEnvelope,
    ArtifactToolOutput,
    PublishedArtifact,
)
from app.sessions.models.conversation import (
    ConversationReadActive,
    ConversationSessionSettings,
    ConversationSnapshot,
    ConversationTurnReservation,
    ConversationTurnResult,
)
from app.sessions.models.execution import ToolExecution
from app.sessions.timeline import timeline
from app.sessions.models.turns import (
    TerminalTurnKind,
    TurnExecutionKind,
)
from app.sessions.limits import MAX_MESSAGE_COUNT, MAX_MESSAGE_LENGTH
from app.sessions.models.session import (
    SessionMessageBusy,
    InvalidMessageReason,
    SessionUnavailableKind,
    TextMessage,
    SessionMessageAppendAccepted,
    SessionMessageAppendExpired,
    SessionMessageAppendInvalidMessage,
    SessionMessageAppendLimitReached,
    SessionMessageAppendOutcome,
    SessionMessageAppendUnknown,
    SessionCreation,
    SessionReadActive,
    SessionReadExpired,
    SessionReadUnknown,
    SessionSnapshot,
)

ContextT = TypeVar("ContextT")
ArtifactT = TypeVar("ArtifactT")


@dataclass(frozen=True)
class _SessionMetadata(Generic[ContextT]):
    expires_at: datetime
    context: ContextT
    settings: ConversationSessionSettings
    owner: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _invalid_text_reason(text: object) -> InvalidMessageReason | None:
    if not isinstance(text, str) or not text.strip():
        return "blank_text"
    if len(text) > MAX_MESSAGE_LENGTH:
        return "text_too_long"
    return None


class TurnHistoryUnavailable(ValueError):
    def __init__(self, kind: SessionUnavailableKind) -> None:
        super().__init__("session turn is no longer active")
        self.kind = kind


class ConversationSessionStore(Generic[ContextT, ArtifactT]):
    def __init__(
        self,
        lifetime: timedelta,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if lifetime <= timedelta():
            raise ValueError("lifetime must be positive")
        self._lifetime = lifetime
        self._clock = clock
        self._lock = RLock()
        self._sessions: dict[str, _SessionMetadata[ContextT]] = {}
        self._active_turns: dict[str, str] = {}
        self._history: dict[str, tuple[HistoryRecord, ...]] = {}
        self._listeners: dict[str, set[Callable[[], None]]] = {}
        self._artifacts: dict[str, dict[str, ArtifactEnvelope[ArtifactT]]] = {}

    def create(
        self, context: ContextT, settings: ConversationSessionSettings, owner: str
    ) -> SessionCreation:
        with self._lock:
            now = self._now()
            self._discard_expired(now)
            session_id = str(uuid4())
            while session_id in self._sessions:
                session_id = str(uuid4())
            expires_at = now + self._lifetime
            self._sessions[session_id] = _SessionMetadata(
                expires_at, deepcopy(context), settings, owner
            )
            self._history[session_id] = ()
            self._artifacts[session_id] = {}
            return SessionCreation(session_id, expires_at)

    def belongs_to(self, session_id: str, owner: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            return session is not None and session.owner == owner

    def read(
        self, session_id: str
    ) -> (
        ConversationReadActive[ContextT, ArtifactT]
        | SessionReadExpired
        | SessionReadUnknown
    ):
        with self._lock:
            outcome = self._read_session(session_id)
            if not isinstance(outcome, SessionReadActive):
                return outcome
            active_turn_id = self._active_turns.get(session_id)
            terminal = self._latest_terminal(session_id)
            return ConversationReadActive(
                kind="active",
                snapshot=ConversationSnapshot(
                    session=outcome.session,
                    artifacts=self._published_artifacts(session_id),
                    terminal_turn_id=terminal.turn_id if terminal else None,
                    terminal_turn_kind=terminal.kind if terminal else None,
                    timeline=timeline(self._history[session_id]),
                    active_turn_id=active_turn_id,
                    active_turn_status=(
                        (
                            "closing"
                            if any(
                                isinstance(record, MessageRecord)
                                and record.turn_id == active_turn_id
                                and record.kind == "final"
                                for record in self._history[session_id]
                            )
                            else "in_progress"
                        )
                        if active_turn_id is not None
                        else None
                    ),
                    sequence=len(self._history[session_id]),
                ),
            )

    def subscribe(
        self, session_id: str, listener: Callable[[], None]
    ) -> Callable[[], None]:
        with self._lock:
            self._listeners.setdefault(session_id, set()).add(listener)
            listener()

        def detach() -> None:
            with self._lock:
                listeners = self._listeners.get(session_id)
                if listeners is not None:
                    listeners.discard(listener)
                    if not listeners:
                        self._listeners.pop(session_id, None)

        return detach

    def _notify(self, session_id: str) -> None:
        for listener in tuple(self._listeners.get(session_id, ())):
            listener()

    def append_user_message(
        self, session_id: str, text: object
    ) -> SessionMessageAppendOutcome:
        with self._lock:
            read = self._read_session(session_id)
            if isinstance(read, SessionReadExpired):
                return SessionMessageAppendExpired(
                    kind="expired", session_id=session_id, expires_at=read.expires_at
                )
            if isinstance(read, SessionReadUnknown):
                return SessionMessageAppendUnknown(kind="unknown", session_id=session_id)
            if session_id in self._active_turns:
                return SessionMessageBusy(session_id=session_id)
            invalid_reason = _invalid_text_reason(text)
            if invalid_reason is not None:
                return SessionMessageAppendInvalidMessage(
                    "invalid_message", session_id, invalid_reason
                )
            if len(read.session.messages) >= MAX_MESSAGE_COUNT - 1:
                return SessionMessageAppendLimitReached("limit_reached", session_id)
            accepted_text = cast(str, text)
            self._append_history(
                session_id,
                MessageRecord(
                    str(uuid4()), {"role": "user", "content": accepted_text}, accepted_text, "user"
                ),
            )
            return SessionMessageAppendAccepted(
                "accepted", session_id, TextMessage("user", accepted_text)
            )

    def admit_turn(
        self, session_id: str
    ) -> (
        ConversationTurnReservation[ContextT, ArtifactT]
        | ConversationTurnResult[ArtifactT]
    ):
        with self._lock:
            read = self._read_session(session_id)
            if not isinstance(read, SessionReadActive):
                return ConversationTurnResult(read.kind, "", None, ())
            active = self._active_turns.get(session_id)
            if active is not None:
                return ConversationTurnResult("busy", active, None, ())
            terminal = self._latest_terminal(session_id)
            if terminal is not None:
                return self._terminal_result(session_id, terminal)
            return self.reserve_turn(session_id)

    def reserve_turn(
        self, session_id: str
    ) -> (
        ConversationTurnReservation[ContextT, ArtifactT]
        | ConversationTurnResult[ArtifactT]
    ):
        with self._lock:
            read = self._read_session(session_id)
            if not isinstance(read, SessionReadActive):
                return ConversationTurnResult(read.kind, "", None, ())
            if session_id in self._active_turns:
                return ConversationTurnResult("busy", "", None, ())
            terminal = self._latest_terminal(session_id)
            if terminal and terminal.kind == "generation_failed":
                return self._terminal_result(session_id, terminal)
            messages = read.session.messages
            if not messages or messages[-1].role != "user":
                return ConversationTurnResult("not_ready", "", None, ())
            if len(messages) >= MAX_MESSAGE_COUNT:
                return ConversationTurnResult("limit_reached", "", None, ())
            turn_id = next(
                record.turn_id
                for record in reversed(self._history[session_id])
                if isinstance(record, MessageRecord)
            )
            self._active_turns[session_id] = turn_id
            self._notify(session_id)
            return ConversationTurnReservation(
                turn_id, read.session, self._published_artifacts(session_id)
            )

    def complete_turn(
        self,
        session_id: str,
        reservation: ConversationTurnReservation[ContextT, ArtifactT],
        kind: TurnExecutionKind,
        text: str | None,
    ) -> ConversationTurnResult[ArtifactT]:
        with self._lock:
            current = self._read_session(session_id)
            if not isinstance(current, SessionReadActive):
                return ConversationTurnResult(
                    current.kind, reservation.turn_id, None, ()
                )
            if self._active_turns.get(session_id) != reservation.turn_id:
                return ConversationTurnResult("conflict", reservation.turn_id, None, ())
            terminal_kind: TerminalTurnKind
            if current.session.revision != reservation.snapshot.revision:
                terminal_kind = "conflict"
            elif kind == "completed" and text is not None:
                if (
                    _invalid_text_reason(text) is None
                    and len(current.session.messages) < MAX_MESSAGE_COUNT
                ):
                    has_final_message = any(
                        isinstance(record, MessageRecord)
                        and record.turn_id == reservation.turn_id
                        and record.kind == "final"
                        for record in self._history[session_id]
                    )
                    if not has_final_message:
                        message = MessageRecord(
                            reservation.turn_id,
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": text,
                                "phase": "final_answer",
                            },
                            text,
                            "final",
                        )
                        self._append_history(session_id, message)
                    terminal_kind = "completed"
                else:
                    terminal_kind = "conflict"
            else:
                terminal_kind = "generation_failed"
            return self._finish_turn(session_id, reservation, terminal_kind)

    def fail_turn(
        self,
        session_id: str,
        reservation: ConversationTurnReservation[ContextT, ArtifactT],
    ) -> ConversationTurnResult[ArtifactT]:
        with self._lock:
            current = self._read_session(session_id)
            if not isinstance(current, SessionReadActive):
                return ConversationTurnResult(
                    current.kind, reservation.turn_id, None, ()
                )
            if self._active_turns.get(session_id) != reservation.turn_id:
                return ConversationTurnResult("conflict", reservation.turn_id, None, ())
            return self._finish_turn(session_id, reservation, "generation_failed")

    def _finish_turn(
        self,
        session_id: str,
        reservation: ConversationTurnReservation[ContextT, ArtifactT],
        kind: TerminalTurnKind,
    ) -> ConversationTurnResult[ArtifactT]:
        self._record_missing_results(session_id, reservation.turn_id)
        terminal = TerminalRecord(reservation.turn_id, kind)
        self._append_history(session_id, terminal)
        self._active_turns.pop(session_id, None)
        self._notify(session_id)
        return self._terminal_result(session_id, terminal)

    def turn_terminal(self, session_id: str, turn_id: str) -> TerminalRecord | None:
        return next(
            (
                record
                for record in reversed(self.history(session_id))
                if isinstance(record, TerminalRecord) and record.turn_id == turn_id
            ),
            None,
        )

    def history(self, session_id: str) -> tuple[HistoryRecord, ...]:
        with self._lock:
            read = self._read_session(session_id)
            if not isinstance(read, SessionReadActive):
                return ()
            return deepcopy(self._history[session_id])

    def record_turn_history(
        self,
        session_id: str,
        turn_id: str,
        records: Iterable[TurnActivityRecord],
    ) -> tuple[TurnActivityRecord, ...]:
        with self._lock:
            self._require_turn(session_id, turn_id)
            accepted: list[TurnActivityRecord] = []
            for record in records:
                self._require_turn(session_id, turn_id)
                if not isinstance(record, (MessageRecord, CallRecord, HostedToolRecord, ContinuationRecord)):
                    raise ValueError("only turn activity can be admitted to history")
                if record.turn_id != turn_id:
                    raise ValueError("history record must belong to the active turn")
                if isinstance(record, MessageRecord) and record.kind == "user":
                    raise ValueError("user messages must use message admission")
                if isinstance(record, MessageRecord) and _invalid_text_reason(record.text) is not None:
                    raise ValueError("assistant message must be nonblank and within the message length limit")
                retained = deepcopy(record)
                self._append_history(session_id, retained)
                accepted.append(deepcopy(retained))
            return tuple(accepted)

    def start_execution(self, session_id: str, call: CallRecord) -> None:
        with self._lock:
            self._require_turn(session_id, call.turn_id)
            self._append_history(
                session_id, ExecutionStartedRecord(call.turn_id, call.execution_id)
            )

    def record_result(
        self,
        session_id: str,
        call: CallRecord,
        execution: ToolExecution[ArtifactCandidate[ArtifactT]],
    ) -> ToolExecution[ArtifactCandidate[ArtifactT]]:
        with self._lock:
            self._require_turn(session_id, call.turn_id)
            history = self._history[session_id]
            if call not in history:
                raise ValueError("result must reference a recorded call")
            if any(
                isinstance(record, (ToolResultRecord, ExecutionReportRecord))
                and record.execution_id == call.execution_id
                for record in history
            ):
                raise ValueError("execution result already recorded")
            output = execution.output
            artifact = execution.artifact
            if artifact is not None:
                if not isinstance(output, ArtifactToolOutput):
                    raise ValueError(
                        "artifact candidates require structured tool output"
                    )
                if (
                    sum(isinstance(record, ArtifactRecord) for record in history)
                    >= self._sessions[session_id].settings.max_artifacts
                ):
                    rejection = json.dumps({"kind": "limit_reached"})
                    finalized = ToolExecution[ArtifactCandidate[ArtifactT]](
                        rejection, failed=True
                    )
                    result = ToolResultRecord(
                        call.turn_id,
                        call.execution_id,
                        call.call_id,
                        rejection,
                        True,
                    )
                    self._history[session_id] = (*history, result)
                    self._notify(session_id)
                    return finalized
                payload = deepcopy(artifact.payload)
                returned_candidate = deepcopy(artifact)
                created_at = self._now()
                if created_at >= self._sessions[session_id].expires_at:
                    self._discard_expired(created_at)
                    raise TurnHistoryUnavailable("expired")
                accepted = ArtifactEnvelope(
                    str(uuid4()), artifact.type, created_at, call.turn_id, payload
                )
                rendered = json.dumps(
                    {"kind": output.kind, "artifact_id": accepted.artifact_id}
                )
                result = ToolResultRecord(
                    call.turn_id,
                    call.execution_id,
                    call.call_id,
                    rendered,
                    execution.failed,
                )
                record = ArtifactRecord(
                    call.turn_id, call.execution_id, accepted.artifact_id
                )
                finalized = ToolExecution(
                    rendered, returned_candidate, execution.failed
                )
                next_history = (*history, result, record)
                next_artifacts = {
                    **self._artifacts[session_id],
                    accepted.artifact_id: accepted,
                }
                self._artifacts[session_id] = next_artifacts
                self._history[session_id] = next_history
                self._notify(session_id)
                return finalized
            if not isinstance(output, str):
                raise ValueError("structured artifact output requires a candidate")
            finalized = ToolExecution[ArtifactCandidate[ArtifactT]](
                output, failed=execution.failed
            )
            self._history[session_id] = (
                *history,
                ToolResultRecord(
                    call.turn_id,
                    call.execution_id,
                    call.call_id,
                    output,
                    execution.failed,
                ),
            )
            self._notify(session_id)
            return finalized

    def _require_turn(self, session_id: str, turn_id: str) -> None:
        outcome = self._read_session(session_id)
        if not isinstance(outcome, SessionReadActive):
            raise TurnHistoryUnavailable(outcome.kind)
        if self._active_turns.get(session_id) != turn_id:
            raise TurnHistoryUnavailable("unknown")

    def _append_history(self, session_id: str, record: HistoryRecord) -> None:
        self._history[session_id] = (*self._history[session_id], record)
        self._notify(session_id)

    def _published_artifacts(
        self, session_id: str
    ) -> tuple[PublishedArtifact[ArtifactT], ...]:
        artifacts: list[PublishedArtifact[ArtifactT]] = []
        for position, record in enumerate(self._history[session_id], start=1):
            if isinstance(record, ArtifactRecord):
                artifact = self._artifacts[session_id][record.artifact_id]
                artifacts.append(
                    PublishedArtifact(
                        artifact.artifact_id,
                        artifact.type,
                        artifact.created_at,
                        artifact.turn_id,
                        deepcopy(artifact.payload),
                        position,
                    )
                )
        return tuple(artifacts)

    def _record_missing_results(self, session_id: str, turn_id: str) -> None:
        history = self._history[session_id]
        started = {
            record.execution_id
            for record in history
            if isinstance(record, ExecutionStartedRecord)
        }
        returned = {
            record.execution_id
            for record in history
            if isinstance(record, (ToolResultRecord, ExecutionReportRecord))
        }
        for record in history:
            if (
                isinstance(record, CallRecord)
                and record.turn_id == turn_id
                and record.execution_id not in returned
            ):
                state = (
                    "outcome_unknown"
                    if record.execution_id in started
                    else "not_executed"
                )
                self._append_history(
                    session_id,
                    ExecutionReportRecord(
                        turn_id, record.execution_id, record.call_id, state
                    ),
                )

    def _latest_terminal(self, session_id: str) -> TerminalRecord | None:
        for record in reversed(self._history[session_id]):
            if isinstance(record, TerminalRecord):
                return record
            if isinstance(record, MessageRecord) and record.kind == "user":
                return None
        return None

    def _terminal_result(
        self, session_id: str, terminal: TerminalRecord
    ) -> ConversationTurnResult[ArtifactT]:
        if terminal.kind != "completed":
            return ConversationTurnResult(terminal.kind, terminal.turn_id, None, ())
        text = next(
            message.text
            for message in completed_text_messages(self._history[session_id])
            if message.role == "assistant" and message.turn_id == terminal.turn_id
        )
        artifacts = tuple(
            artifact
            for artifact in self._published_artifacts(session_id)
            if artifact.turn_id == terminal.turn_id
        )
        return ConversationTurnResult("completed", terminal.turn_id, text, artifacts)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    def _read_session(
        self, session_id: str
    ) -> (
        SessionReadActive[ContextT]
        | SessionReadExpired
        | SessionReadUnknown
    ):
        now = self._now()
        session = self._sessions.get(session_id)
        self._discard_expired(now)
        if session is None:
            return SessionReadUnknown("unknown", session_id)
        if now >= session.expires_at:
            return SessionReadExpired("expired", session_id, session.expires_at)
        messages = completed_text_messages(self._history[session_id])
        return SessionReadActive(
            "active",
            SessionSnapshot(
                session_id,
                session.expires_at,
                len(messages),
                deepcopy(session.context),
                messages,
            ),
        )

    def _discard_expired(self, now: datetime) -> None:
        for session_id, session in tuple(self._sessions.items()):
            if now >= session.expires_at:
                self._discard(session_id)

    def _discard(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._history.pop(session_id, None)
        self._artifacts.pop(session_id, None)
        self._active_turns.pop(session_id, None)
        self._notify(session_id)
