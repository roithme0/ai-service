export interface ChatUsageSummary {
  readonly totalTokens: number;
  readonly estimatedCostUsd: string | null;
}

export interface ChatUsage extends ChatUsageSummary {
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly reasoningTokens: number;
  readonly cacheReadTokens: number;
  readonly cacheWriteTokens: number;
  readonly requests: number;
  readonly toolCalls: number;
}
