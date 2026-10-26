import { Component, computed, ElementRef, input, output, viewChild } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { PreventPointerFocusDirective } from '../../directives/prevent-pointer-focus.directive';
import type { ChatUsage } from '../../models/chat-usage';
import { formatUsageCost } from '../../formatting/usage-format';
import { formatTokens } from '../../formatting/token-format';

const COUNT_FORMAT = new Intl.NumberFormat('en-US');

@Component({
  selector: 'ai-chat-usage-panel',
  imports: [MatIconModule, PreventPointerFocusDirective],
  templateUrl: './usage-panel.component.html',
  styleUrl: './usage-panel.component.scss',
})
export class UsagePanelComponent {
  readonly usage = input.required<ChatUsage>();
  readonly collapsed = output<MouseEvent | KeyboardEvent>();
  private readonly collapseButton =
    viewChild.required<ElementRef<HTMLButtonElement>>('collapseButton');
  protected readonly cost = computed(() => {
    const cost = this.usage().estimatedCostUsd;
    return cost === null ? 'Unbekannt' : formatUsageCost(cost);
  });
  protected readonly metrics = computed(() => {
    const usage = this.usage();
    const tokens = [
      { label: 'Input', value: usage.inputTokens },
      { label: 'Output', value: usage.outputTokens },
      { label: 'Reasoning', value: usage.reasoningTokens },
      { label: 'Gesamt', value: usage.totalTokens },
      { label: 'Cache lesen', value: usage.cacheReadTokens },
      { label: 'Cache schreiben', value: usage.cacheWriteTokens },
    ].map((metric) => ({
      label: metric.label,
      value: formatTokens(metric.value),
      exactValue: metric.value.toString(),
    }));
    return [
      ...tokens,
      {
        label: 'Tool-Aufrufe',
        value: COUNT_FORMAT.format(usage.toolCalls),
        exactValue: usage.toolCalls.toString(),
      },
      {
        label: 'Requests',
        value: COUNT_FORMAT.format(usage.requests),
        exactValue: usage.requests.toString(),
      },
    ];
  });

  focusCollapseButton(): void {
    this.collapseButton().nativeElement.focus({ preventScroll: true });
  }

  protected collapseFromKeyboard(event: Event): void {
    if (event instanceof KeyboardEvent) this.collapsed.emit(event);
  }
}
