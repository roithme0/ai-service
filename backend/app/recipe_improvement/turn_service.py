"""Prepare model input and orchestrate one recipe-improvement turn."""

from __future__ import annotations

import asyncio
import logging

from app.models.agentic_generation import AgenticGenerator
from app.recipe_improvement.agentic_turns import (
    MAX_PROVIDER_RESPONSES, MAX_TOOL_ATTEMPTS, MAX_TOOL_SUCCESSES,
    generate_agentic_recipe_turn,
)
from app.recipe_improvement.artifact_handler import RecipeProposalAttempt, RecipeProposalHandler
from app.recipe_improvement.context import recipe_context
from app.recipe_improvement.instructions import RECIPE_IMPROVEMENT_INSTRUCTIONS
from app.recipe_improvement.proposals import (
    ProposalRegistered,
    ProposalRegistrationOutcome,
    ProposalRejected,
    ProposalSessionUnavailable,
    RecipeProposalPayload,
    proposal_from_artifact,
)
from app.recipe_improvement.tools.register_recipe_proposal import (
    RecipeToolFactory, proposal_registration_tool,
)
from app.recipe_improvement.resolver import RecipePresentationResolver
from app.recipe_improvement.session_lifecycle import (
    RECIPE_ARTIFACT_TYPE,
    RecipeImprovementSessionStore,
)
from app.recipe_improvement.session_input import RecipeImprovementSessionInput
from app.sessions.artifacts import ArtifactPreparationRejected, ArtifactRegistry
from app.sessions.conversation import ConversationStageAccepted, ConversationStageRejected, ConversationTurnResult

logger = logging.getLogger(__name__)


class RecipeTurnStrategy:
    def __init__(
        self, store: RecipeImprovementSessionStore, generator: AgenticGenerator,
        resolver: RecipePresentationResolver,
        instructions: str = RECIPE_IMPROVEMENT_INSTRUCTIONS,
        tool_factory: RecipeToolFactory = proposal_registration_tool,
        max_attempts: int = MAX_TOOL_ATTEMPTS,
        max_successes: int = MAX_TOOL_SUCCESSES,
        max_provider_responses: int = MAX_PROVIDER_RESPONSES,
    ) -> None:
        if not instructions.strip():
            raise ValueError("instructions must not be blank")
        if min(max_attempts, max_successes, max_provider_responses) < 1:
            raise ValueError("recipe turn limits must be positive")
        self._store = store
        self._generator = generator
        self._registry = ArtifactRegistry(((RECIPE_ARTIFACT_TYPE, RecipeProposalHandler(resolver)),))
        self._instructions = instructions
        self._tool_factory = tool_factory
        self._max_attempts = max_attempts
        self._max_successes = max_successes
        self._max_provider_responses = max_provider_responses

    async def __call__(self, session_id: str) -> ConversationTurnResult[RecipeProposalPayload]:
        return await generate_recipe_turn(
            self._store, session_id, self._generator, registry=self._registry,
            instructions=self._instructions, tool_factory=self._tool_factory,
            max_attempts=self._max_attempts, max_successes=self._max_successes,
            max_provider_responses=self._max_provider_responses,
        )


async def generate_recipe_turn(
    store: RecipeImprovementSessionStore,
    session_id: str,
    generator: AgenticGenerator,
    resolver: RecipePresentationResolver | None = None,
    *,
    registry: ArtifactRegistry[RecipeImprovementSessionInput, RecipeProposalPayload, ProposalRejected] | None = None,
    instructions: str = RECIPE_IMPROVEMENT_INSTRUCTIONS,
    tool_factory: RecipeToolFactory = proposal_registration_tool,
    max_attempts: int = MAX_TOOL_ATTEMPTS,
    max_successes: int = MAX_TOOL_SUCCESSES,
    max_provider_responses: int = MAX_PROVIDER_RESPONSES,
) -> ConversationTurnResult[RecipeProposalPayload]:
    if registry is None:
        if resolver is None:
            raise ValueError("resolver or registry is required")
        registry = ArtifactRegistry(((RECIPE_ARTIFACT_TYPE, RecipeProposalHandler(resolver)),))
    reservation = store.reserve_turn(session_id)
    if isinstance(reservation, ConversationTurnResult):
        return reservation

    try:
        context = recipe_context(
            reservation.snapshot.payload,
            tuple(proposal_from_artifact(artifact) for artifact in reservation.previous_artifacts),
        )

        async def register_from_tool(
            base: object, candidate: object
        ) -> ProposalRegistrationOutcome:
            logger.info(
                "Recipe proposal attempt (session_id=%s, turn_id=%s, base=%r, candidate=%r)",
                session_id, reservation.turn_id, base, candidate,
            )
            registration = await registry.register(
                store, session_id, reservation.turn_id, RECIPE_ARTIFACT_TYPE,
                RecipeProposalAttempt(base, candidate),
            )
            if isinstance(registration, ConversationStageAccepted):
                outcome: ProposalRegistrationOutcome = ProposalRegistered(
                    proposal=proposal_from_artifact(registration.artifact)
                )
            elif isinstance(registration, ArtifactPreparationRejected):
                outcome = registration.detail
            elif isinstance(registration, ConversationStageRejected):
                if registration.kind == "missing_reference":
                    outcome = ProposalRejected(reason="invalid_base")
                elif registration.kind == "limit_reached":
                    outcome = ProposalRejected(reason="limit_reached")
                else:
                    outcome = ProposalSessionUnavailable(
                        kind="expired" if registration.kind == "expired" else "unknown"
                    )
            else:
                raise AssertionError("recipe artifact handler was not registered")
            if isinstance(outcome, ProposalRejected):
                logger.warning(
                    "Recipe proposal rejected (session_id=%s, turn_id=%s, stage=%s, outcome=%s, base=%r, candidate=%r)",
                    session_id, reservation.turn_id,
                    registration.stage if isinstance(registration, ArtifactPreparationRejected) else "staging",
                    outcome.model_dump(mode="json"), base, candidate,
                )
            logger.info(
                "Recipe proposal registration (session_id=%s, turn_id=%s, kind=%s, proposal_id=%s)",
                session_id, reservation.turn_id, outcome.kind,
                outcome.proposal.proposal_id if isinstance(outcome, ProposalRegistered) else None,
            )
            return outcome

        result = await generate_agentic_recipe_turn(
            generator,
            reservation.snapshot.messages,
            context,
            instructions,
            register_from_tool,
            tool_factory,
            max_attempts,
            max_successes,
            max_provider_responses,
        )
        return store.complete_turn(session_id, reservation, result.kind, result.text)
    except asyncio.CancelledError:
        store.fail_turn(session_id, reservation)
        raise
    except Exception:
        logger.exception(
            "Recipe turn generation failed (session_id=%s, turn_id=%s)",
            session_id,
            reservation.turn_id,
        )
        return store.fail_turn(session_id, reservation)
