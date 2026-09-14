"""Recipe-improvement adapter for the shared ephemeral text-session core."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.recipe_improvement.proposals import (
    MAX_PROPOSALS_PER_SESSION,
    PreviousProposalBase,
    ProposalBase,
    ProposalRegistered,
    ProposalRegistrationOutcome,
    ProposalRejected,
    ProposalSessionUnavailable,
    RecipeProposal,
)
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.recipe_improvement.validation import RecipeProposalValidationFailure, validate_recipe_proposal
from app.sessions.text_sessions import (
    EphemeralTextSessionStore,
    MAX_MESSAGE_COUNT,
    TextMessage,
    TextSessionSnapshot,
    TextSessionAppendOutcome,
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionReadActive,
    TextSessionReadExpired,
    TextSessionReadUnknown,
)
from app.sessions.tool_turns import ToolTurnResult


SESSION_LIFETIME = timedelta(minutes=90)


class RecipeImprovementSessionCreation(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime


class RecipeImprovementSessionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime
    session_input: RecipeImprovementSessionInput
    messages: tuple[TextMessage, ...] = ()
    proposals: tuple[RecipeProposal, ...] = ()
    terminal_turn_id: str | None = None
    terminal_turn_kind: str | None = None


@dataclass(frozen=True)
class RecipeTurnResult:
    kind: Literal["completed", "generation_failed", "unknown", "expired", "not_ready", "limit_reached", "conflict", "busy"]
    turn_id: str
    text: str | None
    proposals: tuple[RecipeProposal, ...]


@dataclass(frozen=True)
class RecipeTurnReservation:
    turn_id: str
    snapshot: TextSessionSnapshot[RecipeImprovementSessionInput]
    previous_proposals: tuple[RecipeProposal, ...]


@dataclass(frozen=True)
class RecipeMessageBusy:
    session_id: str
    kind: Literal["busy"] = "busy"


RecipeMessageAppendOutcome = TextSessionAppendOutcome | RecipeMessageBusy


@dataclass(frozen=True)
class _TerminalTurn:
    revision: int
    result: RecipeTurnResult


class RecipeImprovementSessionLookupSuccess(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["success"] = "success"
    session: RecipeImprovementSessionSnapshot


class RecipeImprovementSessionLookupUnknown(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown"] = "unknown"
    session_id: str


class RecipeImprovementSessionLookupExpired(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["expired"] = "expired"
    session_id: str = Field(min_length=1)
    expires_at: datetime


RecipeImprovementSessionLookupOutcome = (
    RecipeImprovementSessionLookupSuccess
    | RecipeImprovementSessionLookupUnknown
    | RecipeImprovementSessionLookupExpired
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecipeImprovementSessionStore:
    """Apply the recipe-improvement lifetime policy to the shared session core."""

    def __init__(
        self,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._core = EphemeralTextSessionStore[RecipeImprovementSessionInput](
            lifetime=SESSION_LIFETIME, clock=clock
        )
        self._clock = clock
        self._proposals: dict[str, tuple[RecipeProposal, ...]] = {}
        self._lock = RLock()
        self._active_turns: dict[str, str] = {}
        self._terminal_turns: dict[str, _TerminalTurn] = {}

    def create(
        self, session_input: RecipeImprovementSessionInput
    ) -> RecipeImprovementSessionCreation:
        with self._lock:
            tracked_session_ids = (
                self._proposals.keys() | self._active_turns.keys() | self._terminal_turns.keys()
            )
            for session_id in tuple(tracked_session_ids):
                if not isinstance(self._core.read(session_id), TextSessionReadActive):
                    self._proposals.pop(session_id, None)
                    self._active_turns.pop(session_id, None)
                    self._terminal_turns.pop(session_id, None)
            created = self._core.create(session_input)
            return RecipeImprovementSessionCreation(
                session_id=created.session_id, expires_at=created.expires_at
            )

    def lookup(self, session_id: str) -> RecipeImprovementSessionLookupOutcome:
        with self._lock:
            outcome = self._core.read(session_id)
            if isinstance(outcome, TextSessionReadActive):
                terminal = self._terminal_turns.get(session_id)
                return RecipeImprovementSessionLookupSuccess(
                    session=RecipeImprovementSessionSnapshot(
                        session_id=outcome.session.session_id,
                        expires_at=outcome.session.expires_at,
                        session_input=outcome.session.payload,
                        messages=outcome.session.messages,
                        proposals=self._proposals.get(session_id, ()),
                        terminal_turn_id=terminal.result.turn_id if terminal is not None else None,
                        terminal_turn_kind=terminal.result.kind if terminal is not None else None,
                    )
                )
            self._proposals.pop(session_id, None)
            self._active_turns.pop(session_id, None)
            self._terminal_turns.pop(session_id, None)
            if isinstance(outcome, TextSessionReadExpired):
                return RecipeImprovementSessionLookupExpired(
                    session_id=outcome.session_id, expires_at=outcome.expires_at
                )
            assert isinstance(outcome, TextSessionReadUnknown)
            return RecipeImprovementSessionLookupUnknown(session_id=outcome.session_id)

    def register_proposal(
        self, session_id: str, base: ProposalBase, candidate: object, turn_id: str
    ) -> ProposalRegistrationOutcome:
        with self._lock:
            if self._active_turns.get(session_id) != turn_id:
                return ProposalSessionUnavailable(kind="unknown")
            outcome = self._core.read(session_id)
            if not isinstance(outcome, TextSessionReadActive):
                self._proposals.pop(session_id, None)
                return ProposalSessionUnavailable(kind=outcome.kind)

            proposals = self._proposals.get(session_id, ())
            if isinstance(base, PreviousProposalBase) and not any(
                proposal.proposal_id == base.proposal_id for proposal in proposals
            ):
                return ProposalRejected(reason="invalid_base")
            if len(proposals) >= MAX_PROPOSALS_PER_SESSION:
                return ProposalRejected(reason="limit_reached")

            session_input = outcome.session.payload
            validation = validate_recipe_proposal(
                session_input.source.model_dump(),
                session_input.availability_reference_index,
                candidate,
            )
            if isinstance(validation, RecipeProposalValidationFailure):
                return ProposalRejected(reason="invalid_candidate", issues=validation.issues)

            proposal = RecipeProposal(
                proposal_id=str(uuid4()),
                created_at=self._clock().astimezone(UTC),
                order=len(proposals) + 1,
                base=base,
                recipe=validation.candidate,
                turn_id=turn_id,
            )
            self._proposals[session_id] = (*proposals, proposal)
            return ProposalRegistered(proposal=proposal)

    def append_user_message(self, session_id: str, text: object) -> RecipeMessageAppendOutcome:
        with self._lock:
            read = self._core.read(session_id)
            if isinstance(read, TextSessionReadExpired):
                self._proposals.pop(session_id, None)
                self._active_turns.pop(session_id, None)
                self._terminal_turns.pop(session_id, None)
                return TextSessionAppendExpired(
                    kind="expired", session_id=session_id, expires_at=read.expires_at
                )
            if session_id in self._active_turns:
                return RecipeMessageBusy(session_id=session_id)
            appended = self._core.append_with_max_message_count(
                session_id, "user", text, MAX_MESSAGE_COUNT - 1
            )
            if isinstance(appended, TextSessionAppendAccepted):
                self._terminal_turns.pop(session_id, None)
            return appended

    def _drop_turn_proposals(self, session_id: str, turn_id: str) -> None:
        retained = tuple(
            proposal for proposal in self._proposals.get(session_id, ())
            if proposal.turn_id != turn_id
        )
        if retained:
            self._proposals[session_id] = retained
        else:
            self._proposals.pop(session_id, None)

    def reserve_turn(self, session_id: str) -> RecipeTurnReservation | RecipeTurnResult:
        with self._lock:
            read = self._core.read(session_id)
            if isinstance(read, TextSessionReadExpired):
                self._proposals.pop(session_id, None)
                self._active_turns.pop(session_id, None)
                self._terminal_turns.pop(session_id, None)
                return RecipeTurnResult("expired", "", None, ())
            if not isinstance(read, TextSessionReadActive):
                return RecipeTurnResult("unknown", "", None, ())
            if session_id in self._active_turns:
                return RecipeTurnResult("busy", "", None, ())
            terminal = self._terminal_turns.get(session_id)
            if terminal is not None and terminal.revision == read.session.revision and terminal.result.kind == "generation_failed":
                return terminal.result
            if not read.session.messages or read.session.messages[-1].role != "user":
                return RecipeTurnResult("not_ready", "", None, ())
            if len(read.session.messages) >= MAX_MESSAGE_COUNT:
                return RecipeTurnResult("limit_reached", "", None, ())
            turn_id = str(uuid4())
            self._active_turns[session_id] = turn_id
            return RecipeTurnReservation(turn_id, read.session, self._proposals.get(session_id, ()))

    def complete_turn(
        self, session_id: str, reservation: RecipeTurnReservation, result: ToolTurnResult[RecipeProposal]
    ) -> RecipeTurnResult:
        turn_id, snapshot = reservation.turn_id, reservation.snapshot
        with self._lock:
            current = self._core.read(session_id)
            if not isinstance(current, TextSessionReadActive):
                final = RecipeTurnResult(current.kind, turn_id, None, ())
            elif current.session.revision != snapshot.revision:
                final = RecipeTurnResult("conflict", turn_id, None, ())
            elif result.kind == "completed" and result.text is not None:
                appended = self._core.append_if_revision(session_id, snapshot.revision, "assistant", result.text)
                if isinstance(appended, TextSessionAppendAccepted):
                    final = RecipeTurnResult("completed", turn_id, result.text, result.artifacts)
                else:
                    final = RecipeTurnResult("conflict", turn_id, None, ())
            else:
                final = RecipeTurnResult("generation_failed", turn_id, None, ())
            return self._finish_turn(session_id, reservation, final)

    def fail_turn(self, session_id: str, reservation: RecipeTurnReservation) -> RecipeTurnResult:
        with self._lock:
            current = self._core.read(session_id)
            if not isinstance(current, TextSessionReadActive):
                final = RecipeTurnResult(current.kind, reservation.turn_id, None, ())
            else:
                final = RecipeTurnResult("generation_failed", reservation.turn_id, None, ())
            return self._finish_turn(session_id, reservation, final)

    def _finish_turn(
        self, session_id: str, reservation: RecipeTurnReservation, final: RecipeTurnResult
    ) -> RecipeTurnResult:
        """Commit terminal state while the store lock is held."""
        if final.kind in ("expired", "unknown"):
            self._proposals.pop(session_id, None)
            self._terminal_turns.pop(session_id, None)
        else:
            if final.kind != "completed":
                self._drop_turn_proposals(session_id, reservation.turn_id)
            terminal_revision = reservation.snapshot.revision
            if final.kind == "completed":
                terminal_revision += 1
            self._terminal_turns[session_id] = _TerminalTurn(terminal_revision, final)
        self._active_turns.pop(session_id, None)
        return final
