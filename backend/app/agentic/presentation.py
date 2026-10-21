"""Stateless, explicitly selected presentation of native session state."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field
from pydantic_ai.messages import (
    NativeToolCallPart,
    NativeToolReturnPart,
    RetryPromptPart,
    TextPart,
    TextContent,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agentic.session_state import (
    INITIAL_CONTEXT_ORIGIN, SessionArtifact, TurnLifecycle, TurnStatus,
)
from app.agentic.sessions import SessionSnapshot
from app.agentic.response import ResponseModel
from app.agentic.artifacts import PublishedArtifact

type ToolStatus = Literal[
    "requested", "running", "success", "failed", "denied", "interrupted"
]


class UserPrompt(ResponseModel):
    part_kind: Literal["user-prompt"] = "user-prompt"
    content: str | tuple[str, ...]


class AssistantText(ResponseModel):
    part_kind: Literal["text"] = "text"
    content: str
    phase: Literal["commentary", "final_answer"] | None = None


class ToolActivity(ResponseModel):
    part_kind: Literal["tool-call", "builtin-tool-call"]
    tool_name: str
    tool_call_id: str
    status: ToolStatus


class AcceptedArtifact(ResponseModel):
    part_kind: Literal["artifact"] = "artifact"
    artifact: PublishedArtifact


type PresentationPart = Annotated[
    AssistantText | ToolActivity | AcceptedArtifact,
    Field(discriminator="part_kind"),
]


class PresentedTurn(ResponseModel):
    part_kind: Literal["turn"] = "turn"
    lifecycle: TurnLifecycle
    parts: tuple[PresentationPart, ...]


type HistoryItem = Annotated[UserPrompt | PresentedTurn, Field(discriminator="part_kind")]


class PresentedSession(ResponseModel):
    session_id: str
    expires_at: datetime
    history: tuple[HistoryItem, ...]
    error: Literal["conversation_limit_reached"] | None


@dataclass
class _RunSection:
    run_id: str
    parts: list[PresentationPart] = field(default_factory=list)


def _return_status(part: ToolReturnPart | NativeToolReturnPart) -> ToolStatus:
    # OpenAI's native search adapter retains provider status in content, not outcome.
    if (
        isinstance(part, NativeToolReturnPart)
        and part.provider_name == "openai"
        and part.tool_name == "web_search"
        and part.outcome == "success"
        and isinstance(part.content, dict)
    ):
        match part.content.get("status"):
            case "completed":
                return "success"
            case "failed":
                return "failed"
            case "in_progress" | "searching":
                return "interrupted"
    return part.outcome


def _present_text(part: TextPart) -> AssistantText:
    phase = (part.provider_details or {}).get("phase")
    return AssistantText(
        content=part.content,
        phase=phase if phase in ("commentary", "final_answer") else None,
    )


def _initial_tool_status(turn_status: TurnStatus, *, started: bool) -> ToolStatus:
    if turn_status != "running":
        return "interrupted"
    return "running" if started else "requested"


def _present_artifact(artifact: SessionArtifact) -> AcceptedArtifact:
    return AcceptedArtifact(artifact=PublishedArtifact(
        artifact_id=artifact.artifact_id,
        type=artifact.type,
        created_at=artifact.created_at,
        run_id=artifact.run_id,
        content=artifact.content.model_copy(deep=True),
    ))


def _present_tool_call(
    part: ToolCallPart | NativeToolCallPart,
    *,
    turn_status: TurnStatus,
    started: bool,
    artifacts: Sequence[SessionArtifact],
) -> tuple[ToolActivity | AcceptedArtifact, ...]:
    native = isinstance(part, NativeToolCallPart)
    activity = ToolActivity(
        part_kind="builtin-tool-call" if native else "tool-call",
        tool_name=part.tool_name,
        tool_call_id=part.tool_call_id,
        status=_initial_tool_status(turn_status, started=started),
    )
    if native:
        return (activity,)
    return (activity, *(_present_artifact(artifact) for artifact in artifacts))


def _apply_tool_result(
    activity: ToolActivity,
    result: ToolReturnPart | NativeToolReturnPart | RetryPromptPart,
) -> ToolActivity:
    status = "failed" if isinstance(result, RetryPromptPart) else _return_status(result)
    return activity.model_copy(update={"status": status})


def _update_tool_activity(
    result: ToolReturnPart | NativeToolReturnPart | RetryPromptPart,
    tool_call_locations: dict[tuple[bool, str, str], tuple[_RunSection, int]],
) -> None:
    if result.tool_call_id is None:
        return
    native = isinstance(result, NativeToolReturnPart)
    key = (native, result.tool_call_id, result.tool_name or "")
    if location := tool_call_locations.get(key):
        section, index = location
        activity = section.parts[index]
        assert isinstance(activity, ToolActivity)
        section.parts[index] = _apply_tool_result(activity, result)


def _current_run_section(
    history_sections: list[UserPrompt | _RunSection], run_id: str,
) -> _RunSection:
    previous = history_sections[-1] if history_sections else None
    if isinstance(previous, _RunSection) and previous.run_id == run_id:
        return previous
    section = _RunSection(run_id)
    history_sections.append(section)
    return section


def _present_user_prompt(part: UserPromptPart) -> UserPrompt | None:
    if isinstance(part.content, str):
        return UserPrompt(content=part.content)
    text: list[str] = []
    for item in part.content:
        if isinstance(item, str):
            text.append(item)
        elif (
            isinstance(item, TextContent)
            and (item.metadata or {}).get("origin") != INITIAL_CONTEXT_ORIGIN
        ):
            text.append(item.content)
    return UserPrompt(content=tuple(text)) if text else None


def _present_history(
    history: Sequence[UserPrompt | _RunSection],
    lifecycles: Sequence[TurnLifecycle],
) -> tuple[HistoryItem, ...]:
    turn_positions = {
        lifecycle.run_id: index for index, lifecycle in enumerate(lifecycles)
        if lifecycle.run_id is not None
    }
    result: list[HistoryItem] = []
    next_turn = 0
    for item in history:
        if isinstance(item, UserPrompt):
            result.append(item)
            continue
        position = turn_positions[item.run_id]
        result.extend(
            PresentedTurn(lifecycle=lifecycle, parts=())
            for lifecycle in lifecycles[next_turn:position]
        )
        result.append(PresentedTurn(
            lifecycle=lifecycles[position], parts=tuple(item.parts),
        ))
        next_turn = max(next_turn, position + 1)
    result.extend(
        PresentedTurn(lifecycle=lifecycle, parts=())
        for lifecycle in lifecycles[next_turn:]
    )
    return tuple(result)


def present_session(snapshot: SessionSnapshot) -> PresentedSession:
    """Project an authorized internal snapshot; never retain a presentation history.

    Before native capture, admission has lifecycle metadata only. Interrupted
    activity promises no execution outcome.
    """
    lifecycles_by_run_id = {
        execution.lifecycle.run_id: execution.lifecycle
        for execution in snapshot.turn_executions
        if execution.lifecycle.run_id is not None
    }
    history_sections: list[UserPrompt | _RunSection] = []
    started_tool_calls = {
        (execution.lifecycle.run_id, call.tool_call_id)
        for execution in snapshot.turn_executions
        if execution.observation is not None
        for call in execution.observation.started_tool_calls
    }
    artifacts_by_call: dict[tuple[str, str], list[SessionArtifact]] = {}
    for artifact in snapshot.artifacts:
        artifacts_by_call.setdefault((artifact.run_id, artifact.tool_call_id), []).append(
            artifact
        )
    tool_call_locations: dict[tuple[bool, str, str], tuple[_RunSection, int]] = {}

    for message in snapshot.messages:
        run_id = message.run_id
        for part in message.parts:
            if isinstance(
                part, (ToolReturnPart, NativeToolReturnPart, RetryPromptPart)
            ):
                _update_tool_activity(part, tool_call_locations)
                continue
            if isinstance(part, UserPromptPart):
                if prompt := _present_user_prompt(part):
                    history_sections.append(prompt)
                continue
            if run_id is None or run_id not in lifecycles_by_run_id:
                continue
            if not isinstance(part, (TextPart, ToolCallPart, NativeToolCallPart)):
                continue
            section = _current_run_section(history_sections, run_id)
            parts = section.parts
            if isinstance(part, TextPart):
                parts.append(_present_text(part))
            elif isinstance(part, (ToolCallPart, NativeToolCallPart)):
                native = isinstance(part, NativeToolCallPart)
                tool_call_locations[(native, part.tool_call_id, part.tool_name)] = (
                    section,
                    len(parts),
                )
                parts.extend(_present_tool_call(
                    part,
                    turn_status=lifecycles_by_run_id[run_id].status,
                    started=(run_id, part.tool_call_id) in started_tool_calls,
                    artifacts=artifacts_by_call.get((run_id, part.tool_call_id), ()),
                ))

    return PresentedSession(
        session_id=snapshot.session_id,
        expires_at=snapshot.expires_at,
        error="conversation_limit_reached" if snapshot.limit_reached else None,
        history=_present_history(
            history_sections, tuple(execution.lifecycle for execution in snapshot.turn_executions),
        ),
    )
