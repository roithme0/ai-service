"""Native cumulative limits with a fresh allowance for each turn."""

from decimal import Decimal

from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import RunUsage, UsageLimits

from app.capabilities.conversations.config import (
    MAX_MODEL_REQUESTS_PER_CONVERSATION,
    MAX_MODEL_REQUESTS_PER_TURN,
    MAX_TOOL_CALLS_PER_CONVERSATION,
    MAX_TOOL_CALLS_PER_TURN,
)


class ConversationLimitReached(UsageLimitExceeded):
    """The conversation cannot accept more execution."""


def conversation_limit_reached(usage: RunUsage) -> bool:
    return (
        usage.requests >= MAX_MODEL_REQUESTS_PER_CONVERSATION
        or usage.tool_calls >= MAX_TOOL_CALLS_PER_CONVERSATION
    )


def _absolute_limit(allowance: int | None, used: int) -> int | None:
    return None if allowance is None else used + allowance


def _capped_limit(allowance: int | None, used: int, conversation_cap: int) -> int:
    return (
        conversation_cap
        if allowance is None
        else min(used + allowance, conversation_cap)
    )


def _absolute_cost_limit(
    allowance: Decimal | None, used: Decimal | None
) -> Decimal | None:
    return None if allowance is None else (used or Decimal(0)) + allowance


class _ConversationUsageLimits(UsageLimits):
    """Keep native enforcement, checking conversation caps before turn allowances."""

    def check_before_request(self, usage: RunUsage) -> None:
        if usage.requests >= MAX_MODEL_REQUESTS_PER_CONVERSATION:
            raise ConversationLimitReached("Conversation limit reached")
        super().check_before_request(usage)

    def check_before_tool_call(self, projected_usage: RunUsage) -> None:
        if projected_usage.tool_calls > MAX_TOOL_CALLS_PER_CONVERSATION:
            raise ConversationLimitReached("Conversation limit reached")
        super().check_before_tool_call(projected_usage)


def turn_usage_limits(usage: RunUsage, allowance: UsageLimits | None) -> UsageLimits:
    """Translate cumulative counters; per-request settings keep their native meaning."""
    limits = (
        allowance
        if allowance is not None
        else UsageLimits(
            request_limit=MAX_MODEL_REQUESTS_PER_TURN,
            tool_calls_limit=MAX_TOOL_CALLS_PER_TURN,
        )
    )
    return _ConversationUsageLimits(
        per_request_input_tokens_limit=limits.per_request_input_tokens_limit,
        count_tokens_before_request=limits.count_tokens_before_request,
        request_limit=_capped_limit(
            limits.request_limit,
            usage.requests,
            MAX_MODEL_REQUESTS_PER_CONVERSATION,
        ),
        tool_calls_limit=_capped_limit(
            limits.tool_calls_limit,
            usage.tool_calls,
            MAX_TOOL_CALLS_PER_CONVERSATION,
        ),
        input_tokens_limit=_absolute_limit(
            limits.input_tokens_limit, usage.input_tokens
        ),
        output_tokens_limit=_absolute_limit(
            limits.output_tokens_limit, usage.output_tokens
        ),
        total_tokens_limit=_absolute_limit(
            limits.total_tokens_limit, usage.total_tokens
        ),
        cost_limit=_absolute_cost_limit(limits.cost_limit, usage.cost),
    )
