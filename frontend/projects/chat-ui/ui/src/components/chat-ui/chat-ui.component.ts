import { Component, computed, inject, input, output, viewChild } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import type { DictationConfig } from '../../dictation';
import { registerChatIcons } from '../../chat-icons';
import { ComposerComponent } from '../composer/composer.component';
import { HistoryComponent } from '../history/history.component';
import type { ChatUsage } from '../../models/chat-usage';
import type {
  ChatArtifactRendererMap,
  ChatConversationStatus,
  ChatSubmission,
  ChatTurn,
} from '../../models/chat-message';

@Component({
  selector: 'ai-chat-ui',
  imports: [HistoryComponent, ComposerComponent],
  templateUrl: './chat-ui.component.html',
  styleUrl: './chat-ui.component.scss',
})
export class ChatUiComponent {
  readonly bannerTitle = input<string>();
  readonly bannerDescription = input<string>();
  readonly turns = input.required<readonly ChatTurn[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly usage = input<ChatUsage | null>(null);
  readonly dictation = input<DictationConfig | null>(null);
  readonly dictationContextKey = input<string | null>(null);
  readonly composerDisabled = input(false);
  readonly composerEditingDisabled = input(false);
  readonly composerPlaceholder = input('Nachricht schreiben');
  readonly mascotAssetPath = input('images');

  readonly messageSubmitted = output<ChatSubmission>();
  readonly statusActionTriggered = output<string>();

  private readonly composer = viewChild(ComposerComponent);
  protected readonly history = viewChild(HistoryComponent);
  protected readonly panelScrollClearance = computed(() => this.composer()?.scrollClearance() ?? 0);
  protected readonly messageBoundaryTop = (): number => this.composer()?.messageBoundaryTop() ?? 0;

  protected readonly mascotSource = computed(() => {
    const filename = this.turns().some((turn) => turn.status === 'active')
      ? 'maskot-working.png'
      : 'mascot-idle.png';
    return `${this.mascotAssetPath().replace(/\/$/, '')}/${filename}`;
  });

  constructor() {
    registerChatIcons(inject(MatIconRegistry), inject(DomSanitizer));
  }
}
