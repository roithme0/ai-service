from dataclasses import dataclass
from typing import Generic, TypeVar


ContextT = TypeVar("ContextT")
IssueT = TypeVar("IssueT")


@dataclass(frozen=True)
class AgentInputAccepted(Generic[ContextT]):
    context: ContextT


@dataclass(frozen=True)
class AgentInputRejected(Generic[IssueT]):
    issues: tuple[IssueT, ...]
