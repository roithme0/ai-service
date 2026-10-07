"""Arguments accepted by the agent presentation tool."""

from app.sessions.models.presentation import PresentationPayload


class PresentationRequest(PresentationPayload):
    type: str
