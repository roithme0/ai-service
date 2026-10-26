import { Component, computed, input } from '@angular/core';
import type { ChatUsageSummary } from '../../models/chat-usage';

const TOKEN_FORMAT = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
const COST_FORMAT = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumSignificantDigits: 3,
});

@Component({
  selector: 'ai-chat-usage-line',
  templateUrl: './usage-line.component.html',
  styleUrl: './usage-line.component.scss',
})
export class UsageLineComponent {
  readonly usage = input.required<ChatUsageSummary>();
  protected readonly tokens = computed(() => TOKEN_FORMAT.format(this.usage().totalTokens));
  protected readonly cost = computed(() => {
    const cost = this.usage().estimatedCostUsd;
    return cost === null ? 'Kosten unbekannt' : `Geschätzt ${COST_FORMAT.format(Number(cost))}`;
  });
  protected readonly description = computed(() => {
    const usage = this.usage();
    const cost = usage.estimatedCostUsd;
    return `${cost === null ? 'Kosten unbekannt' : `Geschätzte Kosten: ${cost} USD`}; ${usage.totalTokens} Tokens`;
  });
}
