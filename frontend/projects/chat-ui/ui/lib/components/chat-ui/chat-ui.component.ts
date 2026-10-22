import {
  Component,
  DestroyRef,
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
import { MatIconRegistry } from '@angular/material/icon';
import { registerChatIcons } from '../../chat-icons';
import { HistoryItemComponent } from '../history-item/history-item.component';
import { ToolCallComponent } from '../tool-call/tool-call.component';
import { IntermediateMessageComponent } from '../intermediate-message/intermediate-message.component';
import { UserMessageComponent } from '../user-message/user-message.component';
import { AssistantMessageComponent } from '../assistant-message/assistant-message.component';
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
    HistoryItemComponent,
    ArtifactCardComponent,
    StatusComponent,
    AssistantMessageComponent,
    ComposerComponent,
    ToolCallComponent,
    IntermediateMessageComponent,
    UserMessageComponent,
  ],
  templateUrl: './chat-ui.component.html',
  styleUrl: './chat-ui.component.scss',
})
export class ChatUiComponent {
  private readonly iconRegistry = inject(MatIconRegistry);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly history = viewChild.required<ElementRef<HTMLElement>>('history');

  private scrollHistoryToBottom = false;
  private detailAnchor: { readonly button: HTMLButtonElement; readonly top: number } | null = null;
  private anchorFrame: number | null = null;
  private readonly expandedRuns = signal<ReadonlySet<string>>(new Set());

  readonly bannerTitle = input.required<string>();
  readonly bannerDescription = input.required<string>();
  readonly turns = input.required<readonly ChatTurn[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly composerDisabled = input(false);
  readonly composerEditingDisabled = input(false);
  readonly composerPlaceholder = input('Nachricht schreiben');
  readonly mascotAssetPath = input('images');

  protected readonly sections = computed(() => {
    const occurrences = new Map<string | null, number>();
    return this.turns().map((turn) => {
      const occurrence = occurrences.get(turn.runKey) ?? 0;
      occurrences.set(turn.runKey, occurrence + 1);
      return { turn, key: JSON.stringify([turn.runKey, occurrence]) };
    });
  });

  protected readonly mascotSource = computed(() => {
    const filename = this.turns().some((turn) => turn.status === 'active')
      ? 'maskot-working.png'
      : 'mascot-idle.png';
    return `${this.mascotAssetPath().replace(/\/$/, '')}/${filename}`;
  });

  readonly messageSubmitted = output<ChatSubmission>();
  readonly statusActionTriggered = output<string>();

  protected readonly detailToggleAnchors = computed(() => {
    const answers = new Map<string, string>();
    const groups = new Map<string, ChatTurn[]>();
    for (const turn of this.turns()) {
      const key = turn.runKey;
      if (key === null) continue;
      groups.set(key, [...(groups.get(key) ?? []), turn]);
    }
    for (const [key, turns] of groups) {
      const content = turns.flatMap((turn) => turn.content);
      if (
        turns.some((turn) => turn.status !== 'completed') ||
        !content.some((item) => item.kind === 'intermediate' || item.kind === 'tool')
      )
        continue;
      const answer = content.find(
        (item) => item.kind === 'text' && item.role === 'assistant' && item.isFinal,
      );
      if (answer) answers.set(key, answer.id);
    }
    return answers;
  });
  protected rendererFor(type: string) {
    return this.artifactRenderers()[type] ?? null;
  }

  constructor() {
    inject(DestroyRef).onDestroy(() => this.clearDetailAnchor());
    registerChatIcons(this.iconRegistry, this.sanitizer);
    effect(() => {
      this.turns();
      this.conversationStatus();
      this.scrollHistoryToBottom = true;
    });
    afterEveryRender(() => {
      if (this.detailAnchor && this.anchorFrame === null) this.preserveDetailAnchor();
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

  protected detailsExpanded(turn: ChatTurn): boolean {
    return turn.runKey !== null && this.expandedRuns().has(turn.runKey);
  }

  protected detailsHidden(turn: ChatTurn): boolean {
    return (
      turn.runKey !== null &&
      this.detailToggleAnchors().has(turn.runKey) &&
      !this.detailsExpanded(turn)
    );
  }

  protected toggleDetails(turn: ChatTurn, button: HTMLButtonElement): void {
    const runKey = turn.runKey;
    if (runKey === null || !this.detailToggleAnchors().has(runKey)) return;
    this.clearDetailAnchor();
    this.detailAnchor = { button, top: button.getBoundingClientRect().top };
    const expanded = new Set(this.expandedRuns());
    if (expanded.has(runKey)) {
      expanded.delete(runKey);
    } else {
      expanded.add(runKey);
    }
    this.expandedRuns.set(expanded);
  }

  private preserveDetailAnchor(): void {
    this.anchorFrame = null;
    const anchor = this.detailAnchor;
    if (!anchor || !anchor.button.isConnected) {
      this.clearDetailAnchor();
      return;
    }
    const history = this.history().nativeElement;
    history.scrollTop += anchor.button.getBoundingClientRect().top - anchor.top;
    const transitioning = history
      .getAnimations({ subtree: true })
      .some(
        (animation) =>
          'transitionProperty' in animation &&
          animation.transitionProperty === 'grid-template-rows' &&
          animation.playState === 'running',
      );
    if (transitioning) {
      this.anchorFrame = requestAnimationFrame(() => this.preserveDetailAnchor());
    } else {
      this.detailAnchor = null;
    }
  }

  private clearDetailAnchor(): void {
    if (this.anchorFrame !== null) cancelAnimationFrame(this.anchorFrame);
    this.anchorFrame = null;
    this.detailAnchor = null;
  }
}
