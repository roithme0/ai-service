"""Tools for the deterministic demo."""

from collections.abc import Callable

from app.demo.session import DemoPayload
from app.sessions.artifacts import ArtifactCandidate
from app.sessions.tools import RegisteredTool


type DemoToolFactory = Callable[
    [], RegisteredTool[ArtifactCandidate[DemoPayload]]
]
