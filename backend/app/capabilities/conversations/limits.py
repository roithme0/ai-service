"""Fresh per-turn allowances over cumulative usage accounting."""

from decimal import Decimal

from pydantic_ai.usage import RunUsage, UsageLimits

from app.capabilities.conversations.config import (
    MAX_MODEL_REQUESTS_PER_TURN,
    MAX_TOOL_CALLS_PER_TURN,
)


def _absolute_limit(allowance: int | None, used: int) -> int | None:
    return None if allowance is None else used + allowance


def _absolute_cost_limit(
    allowance: Decimal | None, used: Decimal | None
) -> Decimal | None:
    return None if allowance is None else (used or Decimal(0)) + allowance


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
    return UsageLimits(
        per_request_input_tokens_limit=limits.per_request_input_tokens_limit,
        count_tokens_before_request=limits.count_tokens_before_request,
        request_limit=_absolute_limit(limits.request_limit, usage.requests),
        tool_calls_limit=_absolute_limit(limits.tool_calls_limit, usage.tool_calls),
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
