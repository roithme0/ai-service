import { Component, computed, input } from '@angular/core';
import type { ChatUsageSummary } from '../../models/chat-usage';
import { formatUsageCost } from '../../formatting/usage-format';
import { formatTokens } from '../../formatting/token-format';

@Component({
  selector: 'ai-chat-usage-line',
  templateUrl: './usage-line.component.html',
  styleUrl: './usage-line.component.scss',
})
export class UsageLineComponent {
  readonly usage = input.required<ChatUsageSummary>();
  protected readonly tokens = computed(() => formatTokens(this.usage().totalTokens));
  protected readonly cost = computed(() => {
    const cost = this.usage().estimatedCostUsd;
    return cost === null ? 'Kosten unbekannt' : `Geschätzt ${formatUsageCost(cost)}`;
  });
  protected readonly description = computed(() => {
    const usage = this.usage();
    const cost = usage.estimatedCostUsd;
    return `${cost === null ? 'Kosten unbekannt' : `Geschätzte Kosten: ${cost} USD`}; ${usage.totalTokens} Tokens`;
  });
}
