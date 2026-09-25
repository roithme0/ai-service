"""Recipe conversation settings and typed store construction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TypeAlias

from app.recipe_improvement.proposals import MAX_PROPOSALS_PER_SESSION, RecipeProposalPayload
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.sessions.conversation import ConversationSessionSettings, ConversationSessionStore
from app.sessions.text_sessions import TextSessionCreation

SESSION_LIFETIME = timedelta(minutes=90)
RECIPE_ARTIFACT_TYPE = "recipe.proposal"
RecipeImprovementSessionStore: TypeAlias = ConversationSessionStore[RecipeImprovementSessionInput, RecipeProposalPayload]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def new_recipe_session_store(clock: Callable[[], datetime] = _utc_now) -> RecipeImprovementSessionStore:
    return ConversationSessionStore(lifetime=SESSION_LIFETIME, clock=clock)


def create_recipe_session(
    store: RecipeImprovementSessionStore, session_input: RecipeImprovementSessionInput
) -> TextSessionCreation:
    return store.create(session_input, ConversationSessionSettings(max_artifacts=MAX_PROPOSALS_PER_SESSION))
