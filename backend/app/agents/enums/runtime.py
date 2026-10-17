"""Lifecycle state of a configured agent runtime."""

from enum import StrEnum


class RuntimeStatus(StrEnum):
    CREATED = "created"
    CONNECTING = "connecting"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    CLOSING = "closing"
    CLOSED = "closed"
