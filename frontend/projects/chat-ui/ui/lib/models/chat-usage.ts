export interface ChatUsageSummary {
  readonly totalTokens: number;
  readonly estimatedCostUsd: string | null;
}
