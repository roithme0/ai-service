"""Opt-in configuration for provider-executed web search."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WebSearchConfig:
    max_calls_per_turn: int = 8

    def __post_init__(self) -> None:
        if isinstance(self.max_calls_per_turn, bool) or not isinstance(self.max_calls_per_turn, int) or self.max_calls_per_turn < 1:
            raise ValueError("web search call limit must be a positive integer")
