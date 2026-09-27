"""Tools for the deterministic demo."""

from collections.abc import Callable

from app.demo.session import DemoPayload, DemoSessionStore
from app.sessions.conversation import StagedArtifact
from app.sessions.tools import RegisteredTool


type DemoToolFactory = Callable[
    [DemoSessionStore, str, str], RegisteredTool[StagedArtifact[DemoPayload]]
]
