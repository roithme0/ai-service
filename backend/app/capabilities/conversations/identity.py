"""Task-local assertion retained for background turns and their MCP clients."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.identity import ApplicationIdentity

_turn_identity: ContextVar[ApplicationIdentity] = ContextVar("turn_identity")


@contextmanager
def bind_turn_identity(identity: ApplicationIdentity) -> Iterator[None]:
    token = _turn_identity.set(identity)
    try:
        yield
    finally:
        _turn_identity.reset(token)


def current_turn_identity() -> ApplicationIdentity:
    return _turn_identity.get()
