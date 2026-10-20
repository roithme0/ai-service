import {
  Component,
  ElementRef,
  afterEveryRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconModule, MatIconRegistry } from '@angular/material/icon';
import { renderAssistantMarkdown } from '../../assistant-markdown';
import { registerChatIcons } from '../../chat-icons';
import { ToolCallComponent } from '../tool-call/tool-call.component';
import { IntermediateMessageComponent } from '../intermediate-message/intermediate-message.component';
import { ComposerComponent } from '../composer/composer.component';
import { ArtifactCardComponent } from '../artifact-card/artifact-card.component';
import { StatusComponent } from '../status/status.component';
import type {
  ChatArtifactRendererMap,
  ChatConversationStatus,
  ChatSubmission,
  ChatTurn,
} from '../../models/chat-message';

@Component({
  selector: 'ai-chat-ui',
  imports: [
    ArtifactCardComponent,
    StatusComponent,
    MatIconModule,
    ComposerComponent,
    ToolCallComponent,
    IntermediateMessageComponent,
  ],
  templateUrl: './chat-ui.component.html',
  styleUrl: './chat-ui.component.scss',
})
export class ChatUiComponent {
  private readonly iconRegistry = inject(MatIconRegistry);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly history = viewChild.required<ElementRef<HTMLElement>>('history');

  private scrollHistoryToBottom = false;
  private expandedTurnToScroll: string | null = null;
  private collapsedScrollTop: number | null = null;
  private readonly expandedTurns = signal<ReadonlySet<string>>(new Set());

  readonly bannerTitle = input.required<string>();
  readonly bannerDescription = input.required<string>();
  readonly turns = input.required<readonly ChatTurn[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly composerDisabled = input(false);
  readonly focusOnReady = input(false);
  readonly composerPlaceholder = input('Nachricht schreiben');

  readonly messageSubmitted = output<ChatSubmission>();
  readonly statusActionTriggered = output<string>();

  protected readonly disclosureAnswers = computed(() => {
    const answers = new Map<string, string>();
    for (const turn of this.turns()) {
      if (
        turn.status !== 'completed' ||
        !turn.content.some((item) => item.kind === 'intermediate' || item.kind === 'tool')
      )
        continue;
      const answer = turn.content.find(
        (item) => item.kind === 'text' && item.role === 'assistant' && item.isFinal,
      );
      if (answer) answers.set(turn.id, answer.id);
    }
    return answers;
  });
  protected readonly renderAssistantMarkdown = renderAssistantMarkdown;
  protected rendererFor(type: string) {
    return this.artifactRenderers()[type] ?? null;
  }

  constructor() {
    registerChatIcons(this.iconRegistry, this.sanitizer);
    afterEveryRender(() => {
      const history = this.history().nativeElement;
      if (this.collapsedScrollTop !== null) {
        history.scrollTop = Math.max(
          0,
          Math.min(this.collapsedScrollTop, history.scrollHeight - history.clientHeight),
        );
        this.collapsedScrollTop = null;
      }
      const turnId = this.expandedTurnToScroll;
      if (turnId === null) return;
      this.expandedTurnToScroll = null;
      const anchor = [...history.querySelectorAll<HTMLElement>('[data-turn-start]')].find(
        (item) => item.dataset['turnStart'] === turnId,
      );
      if (!anchor) return;
      const top =
        history.scrollTop +
        anchor.getBoundingClientRect().top -
        history.getBoundingClientRect().top -
        history.clientTop;
      history.scrollTo({
        top: Math.max(0, Math.min(top, history.scrollHeight - history.clientHeight)),
        behavior: 'smooth',
      });
    });
    effect(() => {
      this.turns();
      this.conversationStatus();
      this.scrollHistoryToBottom = true;
    });
    afterEveryRender(() => {
      if (!this.scrollHistoryToBottom) return;
      this.scrollHistoryToBottom = false;
      const history = this.history().nativeElement;
      if (typeof history.scrollTo === 'function') {
        history.scrollTo({ top: history.scrollHeight, behavior: 'smooth' });
      } else {
        history.scrollTop = history.scrollHeight;
      }
    });
  }

  protected requestHistoryScroll(): void {
    this.scrollHistoryToBottom = true;
  }

  protected detailsExpanded(turnId: string): boolean {
    return this.expandedTurns().has(turnId);
  }

  protected detailsHidden(turnId: string): boolean {
    return this.disclosureAnswers().has(turnId) && !this.detailsExpanded(turnId);
  }

  protected toggleDetails(turnId: string): void {
    if (!this.disclosureAnswers().has(turnId)) return;
    const expanded = new Set(this.expandedTurns());
    if (expanded.has(turnId)) {
      this.collapsedScrollTop = this.history().nativeElement.scrollTop;
      expanded.delete(turnId);
      this.expandedTurnToScroll = null;
    } else {
      this.collapsedScrollTop = null;
      expanded.add(turnId);
      this.expandedTurnToScroll = turnId;
    }
    this.expandedTurns.set(expanded);
  }
}
