"""Shared finite JSON value type."""

from pydantic import FiniteFloat

type FiniteJsonValue = (
    dict[str, FiniteJsonValue]
    | list[FiniteJsonValue]
    | str
    | bool
    | int
    | FiniteFloat
    | None
)
