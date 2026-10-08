"""Tools for the deterministic demo."""

from collections.abc import Callable

from app.demo.session import DemoPayload
from app.sessions.models.artifacts import ArtifactCandidate
from app.agents.models.tools import RegisteredTool


type DemoToolFactory = Callable[
    [], RegisteredTool[ArtifactCandidate[DemoPayload]]
]
