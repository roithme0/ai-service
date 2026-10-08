"""Arguments accepted by the agent artifact tool."""

from app.sessions.models.artifacts import ArtifactPayload


class ArtifactRequest(ArtifactPayload):
    type: str
