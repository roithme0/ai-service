"""Artifact dispatch and authoritative lifecycle checks."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.sessions.artifacts import (
    ArtifactPrepared, ArtifactPreparationRejected, ArtifactRegistry, ArtifactTypeUnsupported,
)
from app.sessions.conversation import (
    ConversationReadActive, ConversationSessionSettings, ConversationSessionStore,
    ConversationStageAccepted, ConversationStageRejected, ConversationTurnReservation,
    ConversationTurnView,
)


@dataclass(frozen=True)
class Context:
    name: str


@dataclass(frozen=True)
class Payload:
    message: str


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 25, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class Handler:
    def __init__(self) -> None:
        self.views: list[ConversationTurnView[Context, Payload]] = []
        self.wait: asyncio.Event | None = None
        self.entered: asyncio.Event | None = None
        self.fail = False

    async def prepare(
        self, view: ConversationTurnView[Context, Payload], candidate: object,
    ) -> ArtifactPrepared[Payload] | ArtifactPreparationRejected[str]:
        self.views.append(view)
        if self.entered is not None:
            self.entered.set()
        if self.wait is not None:
            await self.wait.wait()
        if self.fail:
            raise RuntimeError("unexpected preparation failure")
        if not isinstance(candidate, str):
            return ArtifactPreparationRejected("invalid_candidate")
        return ArtifactPrepared(Payload(candidate))


def setup(
    clock: Clock | None = None, limit: int = 2,
) -> tuple[ConversationSessionStore[Context, Payload], str, ConversationTurnReservation[Context, Payload]]:
    source = clock or Clock()
    store = ConversationSessionStore[Context, Payload](timedelta(minutes=90), source.now)
    session_id = store.create(Context("one"), ConversationSessionSettings(limit)).session_id
    store.append_user_message(session_id, "Begin")
    reservation = store.reserve_turn(session_id)
    assert isinstance(reservation, ConversationTurnReservation)
    return store, session_id, reservation


def test_dispatch_rejections_and_envelope_without_mutation() -> None:
    store, session_id, reservation = setup()
    handler = Handler()
    registry = ArtifactRegistry((("example", handler),))
    with pytest.raises(ValueError, match="duplicate artifact handler"):
        ArtifactRegistry((("example", handler), ("example", handler)))

    async def run() -> None:
        unsupported = await registry.register(store, session_id, reservation.turn_id, "missing", "one")
        assert isinstance(unsupported, ArtifactTypeUnsupported)
        assert handler.views == []
        rejected = await registry.register(store, session_id, reservation.turn_id, "example", 4)
        assert rejected == ArtifactPreparationRejected("invalid_candidate")
        view = store.inspect_turn(session_id, reservation.turn_id)
        assert isinstance(view, ConversationTurnView)
        assert view.artifacts == ()
        accepted = await registry.register(store, session_id, reservation.turn_id, "example", "one")
        assert isinstance(accepted, ConversationStageAccepted)
        assert accepted.artifact.type == "example"
        assert accepted.artifact.payload == Payload("one")
        assert accepted.artifact.artifact_id
        assert accepted.artifact.order == 1
        assert accepted.artifact.turn_id == reservation.turn_id
        assert handler.views[-1].snapshot.payload == Context("one")
        assert handler.views[-1].artifacts == ()

    asyncio.run(run())


def test_handler_sees_prior_and_same_turn_artifacts_as_copies() -> None:
    store, session_id, first = setup()
    handler = Handler()
    registry = ArtifactRegistry((("example", handler),))
    prior = asyncio.run(registry.register(store, session_id, first.turn_id, "example", "prior"))
    assert isinstance(prior, ConversationStageAccepted)
    assert store.complete_turn(session_id, first, "completed", "Done").kind == "completed"
    store.append_user_message(session_id, "Continue")
    second = store.reserve_turn(session_id)
    assert isinstance(second, ConversationTurnReservation)
    current = asyncio.run(registry.register(store, session_id, second.turn_id, "example", "current"))
    assert isinstance(current, ConversationStageAccepted)
    asyncio.run(registry.register(store, session_id, second.turn_id, "example", "extra"))
    assert [a.artifact_id for a in handler.views[-1].artifacts] == [
        prior.artifact.artifact_id, current.artifact.artifact_id,
    ]
    assert handler.views[-1].artifacts[0] is not prior.artifact


def test_preparation_rechecks_expiry_and_capacity() -> None:
    clock = Clock()
    store, session_id, reservation = setup(clock, limit=1)
    handler = Handler()
    handler.entered = asyncio.Event()
    handler.wait = asyncio.Event()
    registry = ArtifactRegistry((("example", handler),))

    async def expire() -> None:
        task = asyncio.create_task(registry.register(store, session_id, reservation.turn_id, "example", "late"))
        assert handler.entered is not None and handler.wait is not None
        await handler.entered.wait()
        clock.value += timedelta(minutes=90)
        handler.wait.set()
        result = await task
        assert result == ConversationStageRejected("expired")

    asyncio.run(expire())
    assert store.read(session_id).kind == "unknown"

    store, session_id, reservation = setup(limit=1)
    handler = Handler()
    handler.entered = asyncio.Event()
    handler.wait = asyncio.Event()
    registry = ArtifactRegistry((("example", handler),))

    async def fill_capacity() -> None:
        task = asyncio.create_task(registry.register(store, session_id, reservation.turn_id, "example", "late"))
        assert handler.entered is not None and handler.wait is not None
        await handler.entered.wait()
        assert isinstance(store.stage_artifact(session_id, reservation.turn_id, "example", Payload("first")), ConversationStageAccepted)
        handler.wait.set()
        assert await task == ConversationStageRejected("limit_reached")

    asyncio.run(fill_capacity())


def test_unexpected_handler_failure_uses_turn_cleanup() -> None:
    store, session_id, reservation = setup()
    handler = Handler()
    handler.fail = True
    registry = ArtifactRegistry((("example", handler),))
    store.stage_artifact(session_id, reservation.turn_id, "example", Payload("pending"))

    async def run() -> None:
        with pytest.raises(RuntimeError, match="unexpected preparation failure"):
            await registry.register(store, session_id, reservation.turn_id, "example", "fail")
        assert store.fail_turn(session_id, reservation).kind == "generation_failed"

    asyncio.run(run())
    read = store.read(session_id)
    assert isinstance(read, ConversationReadActive)
    assert read.snapshot.artifacts == ()


def test_preparation_allows_other_sessions_but_rejects_overlapping_turn() -> None:
    store, session_id, reservation = setup()
    other_id = store.create(Context("other"), ConversationSessionSettings(2)).session_id
    store.append_user_message(other_id, "Begin")
    handler = Handler()
    handler.entered = asyncio.Event()
    handler.wait = asyncio.Event()
    registry = ArtifactRegistry((("example", handler),))

    async def run() -> None:
        task = asyncio.create_task(registry.register(store, session_id, reservation.turn_id, "example", "first"))
        assert handler.entered is not None and handler.wait is not None
        await handler.entered.wait()
        assert store.reserve_turn(session_id).kind == "busy"
        assert store.append_user_message(session_id, "Blocked").kind == "busy"
        other = store.reserve_turn(other_id)
        assert isinstance(other, ConversationTurnReservation)
        assert store.complete_turn(other_id, other, "completed", "Done").kind == "completed"
        handler.wait.set()
        assert isinstance(await task, ConversationStageAccepted)

    asyncio.run(run())


def test_preparation_cannot_stage_after_its_turn_fails() -> None:
    store, session_id, reservation = setup()
    handler = Handler()
    handler.entered = asyncio.Event()
    handler.wait = asyncio.Event()
    registry = ArtifactRegistry((("example", handler),))

    async def run() -> None:
        task = asyncio.create_task(registry.register(store, session_id, reservation.turn_id, "example", "late"))
        assert handler.entered is not None and handler.wait is not None
        await handler.entered.wait()
        assert store.fail_turn(session_id, reservation).kind == "generation_failed"
        store.append_user_message(session_id, "Retry")
        next_turn = store.reserve_turn(session_id)
        assert isinstance(next_turn, ConversationTurnReservation)
        handler.wait.set()
        assert await task == ConversationStageRejected("unknown")
        assert isinstance(store.inspect_turn(session_id, next_turn.turn_id), ConversationTurnView)

    asyncio.run(run())
