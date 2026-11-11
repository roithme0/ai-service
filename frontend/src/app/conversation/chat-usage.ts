import type { PresentedSession } from '@roithme0/chat-ui/conversation';
import type { ChatUsage } from '@roithme0/chat-ui/ui';

export function chatUsage(usage: PresentedSession['usage'] | undefined): ChatUsage | null {
  return usage
    ? {
        totalTokens: usage.total_tokens,
        estimatedCostUsd: usage.estimated_cost_usd,
        inputTokens: usage.input_tokens,
        outputTokens: usage.output_tokens,
        reasoningTokens: usage.reasoning_tokens,
        cacheReadTokens: usage.cache_read_tokens,
        cacheWriteTokens: usage.cache_write_tokens,
        requests: usage.requests,
        toolCalls: usage.tool_calls,
      }
    : null;
}
