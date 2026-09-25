"""HTTP adapters for recipe-improvement sessions and agentic turns."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agents.recipe import RecipeAgent, RecipeSessionInput
from app.agents.wiring import get_configured_agents
from app.recipe_improvement.session_input import (
    AvailableFoodstuffSnapshot,
    RecipeImprovementSourceSnapshot,
)
from app.sessions.conversation import ConversationMessageBusy, ConversationReadActive
from app.recipe_improvement.validation import ValidationIssue
from app.sessions.agent_service import AgentInputRejected
from app.sessions.text_sessions import (
    TextMessage,
    TextSessionAppendAccepted,
    TextSessionAppendExpired,
    TextSessionAppendInvalidMessage,
    TextSessionAppendLimitReached,
    TextSessionCreation,
    TextSessionReadExpired,
)
from app.recipe_improvement.proposals import RecipeProposal, proposal_from_artifact


router = APIRouter(prefix="/api/v1/recipe-improvement/sessions", tags=["recipe-improvement"])


class RecipeImprovementSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: object
    foodstuffs: object


class RecipeImprovementSessionInputErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["invalid_input"] = "invalid_input"
    issues: tuple[ValidationIssue, ...]


class RecipeImprovementUserMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str


class RecipeUserMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["user"] = "user"
    text: str


class RecipeAssistantMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["assistant"] = "assistant"
    text: str
    turn_id: str = Field(min_length=1)


RecipeMessageResponse = RecipeUserMessageResponse | RecipeAssistantMessageResponse


class RecipeImprovementSessionReadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    expires_at: datetime
    source: RecipeImprovementSourceSnapshot
    foodstuffs: tuple[AvailableFoodstuffSnapshot, ...]
    messages: tuple[RecipeMessageResponse, ...]
    proposals: tuple[RecipeProposal, ...] = ()
    terminal_turn_id: str | None = None
    terminal_turn_kind: str | None = None


class RecipeImprovementTurnResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    turn_id: str
    message: RecipeAssistantMessageResponse
    proposals: tuple[RecipeProposal, ...] = ()


class AgentUnavailable(Exception):
    pass


def get_recipe_agent() -> RecipeAgent:
    agent = get_configured_agents().recipe
    if agent is None:
        raise AgentUnavailable()
    return agent


@router.post("", response_model=TextSessionCreation, status_code=201)
def create_recipe_improvement_session(
    request: RecipeImprovementSessionCreateRequest,
    agent: RecipeAgent = Depends(get_recipe_agent),
) -> TextSessionCreation | JSONResponse:
    outcome = agent.create(RecipeSessionInput(request.source, request.foodstuffs))
    if isinstance(outcome, AgentInputRejected):
        return _invalid_input_response(outcome)
    return outcome


@router.get("/{session_id}", response_model=RecipeImprovementSessionReadResponse)
def get_recipe_improvement_session(
    session_id: str,
    agent: RecipeAgent = Depends(get_recipe_agent),
) -> RecipeImprovementSessionReadResponse | JSONResponse:
    outcome = agent.read(session_id)
    if isinstance(outcome, ConversationReadActive):
        snapshot = outcome.snapshot
        return RecipeImprovementSessionReadResponse(
            session_id=snapshot.session.session_id,
            expires_at=snapshot.session.expires_at,
            source=snapshot.session.payload.source,
            foodstuffs=snapshot.session.payload.foodstuffs,
            messages=tuple(_message_response(message) for message in snapshot.session.messages),
            proposals=tuple(proposal_from_artifact(a) for a in snapshot.artifacts),
            terminal_turn_id=snapshot.terminal_turn_id,
            terminal_turn_kind=snapshot.terminal_turn_kind,
        )
    if isinstance(outcome, TextSessionReadExpired):
        return JSONResponse(status_code=410, content={"kind": "expired"})
    return JSONResponse(status_code=404, content={"kind": "unknown"})


@router.get("/{session_id}/proposals/{proposal_id}", response_model=RecipeProposal)
def get_recipe_improvement_proposal(
    session_id: str,
    proposal_id: str,
    agent: RecipeAgent = Depends(get_recipe_agent),
) -> RecipeProposal | JSONResponse:
    outcome = agent.read(session_id)
    if isinstance(outcome, TextSessionReadExpired):
        return JSONResponse(status_code=410, content={"kind": "expired"})
    if not isinstance(outcome, ConversationReadActive):
        return JSONResponse(status_code=404, content={"kind": "unknown"})
    for artifact in outcome.snapshot.artifacts:
        proposal = proposal_from_artifact(artifact)
        if proposal.proposal_id == proposal_id:
            return proposal
    return JSONResponse(status_code=404, content={"kind": "unknown_proposal"})


@router.post(
    "/{session_id}/messages",
    response_model=RecipeUserMessageResponse,
    status_code=201,
)
def append_recipe_improvement_user_message(
    session_id: str,
    request: RecipeImprovementUserMessageRequest,
    agent: RecipeAgent = Depends(get_recipe_agent),
) -> RecipeUserMessageResponse | JSONResponse:
    outcome = agent.append_user_message(session_id, request.text)
    if isinstance(outcome, TextSessionAppendAccepted):
        return RecipeUserMessageResponse(text=outcome.message.text)
    if isinstance(outcome, TextSessionAppendExpired):
        return JSONResponse(status_code=410, content={"kind": "expired"})
    if isinstance(outcome, TextSessionAppendLimitReached):
        return JSONResponse(status_code=409, content={"kind": "limit_reached"})
    if isinstance(outcome, TextSessionAppendInvalidMessage):
        return JSONResponse(status_code=422, content={"kind": "invalid_message"})
    if isinstance(outcome, ConversationMessageBusy):
        return JSONResponse(status_code=409, content={"kind": "busy"})
    return JSONResponse(status_code=404, content={"kind": "unknown"})


@router.post(
    "/{session_id}/turns",
    response_model=RecipeImprovementTurnResponse,
    status_code=201,
)
async def generate_recipe_improvement_turn(
    session_id: str,
    agent: RecipeAgent = Depends(get_recipe_agent),
) -> RecipeImprovementTurnResponse | JSONResponse:
    outcome = await agent.execute_turn(session_id)
    if outcome.kind == "completed":
        assert outcome.text is not None
        return RecipeImprovementTurnResponse(
            turn_id=outcome.turn_id,
            message=RecipeAssistantMessageResponse(
                text=outcome.text, turn_id=outcome.turn_id
            ),
            proposals=tuple(proposal_from_artifact(a) for a in outcome.artifacts),
        )
    status_code = {
        "unknown": 404,
        "expired": 410,
        "not_ready": 409,
        "limit_reached": 409,
        "conflict": 409,
        "generation_failed": 502,
        "busy": 409,
    }[outcome.kind]
    content: dict[str, object] = {"kind": outcome.kind}
    if outcome.turn_id:
        content["turn_id"] = outcome.turn_id
    return JSONResponse(status_code=status_code, content=content)


def _invalid_input_response(
    outcome: AgentInputRejected[ValidationIssue],
) -> JSONResponse:
    response = RecipeImprovementSessionInputErrorResponse(issues=outcome.issues)
    return JSONResponse(status_code=422, content=response.model_dump(mode="json"))


def _message_response(message: TextMessage) -> RecipeMessageResponse:
    if message.role == "user":
        return RecipeUserMessageResponse(text=message.text)
    assert message.turn_id is not None
    return RecipeAssistantMessageResponse(text=message.text, turn_id=message.turn_id)
