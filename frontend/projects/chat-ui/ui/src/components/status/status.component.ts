import { Component, computed, effect, input, output, signal } from '@angular/core';
import type { EffectCleanupRegisterFn } from '@angular/core';
import { LoadingDotsComponent } from '../loading-dots/loading-dots.component';
import type { ChatConversationStatus } from '../../models/chat-message';

@Component({
  selector: 'ai-chat-status',
  imports: [LoadingDotsComponent],
  templateUrl: './status.component.html',
  styleUrl: './status.component.scss',
  host: {
    role: 'article',
    '[class.error]': "status().kind === 'error'",
    '[class.delayed]': "status().kind === 'loading' && status().reveal === 'delayed'",
  },
})
export class StatusComponent {
  readonly status = input.required<ChatConversationStatus>();
  readonly actionTriggered = output<string>();
  readonly contentRevealed = output<void>();
  private readonly revealedStatus = signal<ChatConversationStatus | null>(null);
  protected readonly visible = computed(() => {
    const status = this.status();
    return (
      status.kind !== 'loading' || status.reveal !== 'delayed' || this.revealedStatus() === status
    );
  });

  constructor() {
    effect((onCleanup) => this.updateStatusVisibility(onCleanup));
  }

  private updateStatusVisibility(onCleanup: EffectCleanupRegisterFn): void {
    const status = this.status();
    this.revealedStatus.set(null);
    if (status.kind !== 'loading' || status.reveal !== 'delayed') return;
    const timer = setTimeout(() => {
      this.revealedStatus.set(status);
      this.contentRevealed.emit();
    }, 300);
    onCleanup(() => clearTimeout(timer));
  }
}
