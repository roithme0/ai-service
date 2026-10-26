import {
  Component,
  ElementRef,
  afterEveryRender,
  afterNextRender,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
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
import type { ChatUsage } from '../../models/chat-usage';
import type {
  ChatArtifactRendererMap,
  ChatContent,
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
  private readonly destroyRef = inject(DestroyRef);

  private readonly historyViewport = viewChild<ElementRef<HTMLElement>>('historyViewport');
  private readonly historyContent = viewChild.required<ElementRef<HTMLElement>>('historyContent');
  private readonly composer = viewChild(ComposerComponent);

  protected readonly panelScrollClearance = computed(() => this.composer()?.scrollClearance() ?? 0);

  private historyScrollPending = false;
  private followingHistory = true;
  protected readonly scrollAnchor = signal<string | null>(null);
  private readonly expandedRuns = signal<ReadonlySet<string>>(new Set());
  private readonly initializedRuns = new Map<string, boolean>();

  readonly bannerTitle = input<string>();
  readonly bannerDescription = input.required<string>();
  readonly turns = input.required<readonly ChatTurn[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly usage = input<ChatUsage | null>(null);
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

  protected readonly detailRuns = computed(() => {
    const answers = new Map<string, { readonly answerId: string; readonly completed: boolean }>();
    const groups = new Map<string, ChatTurn[]>();
    for (const turn of this.turns()) {
      const key = turn.runKey;
      if (key === null) continue;
      groups.set(key, [...(groups.get(key) ?? []), turn]);
    }
    for (const [key, turns] of groups) {
      const content = turns.flatMap((turn) => turn.content);
      if (!content.some((item) => item.kind === 'intermediate' || item.kind === 'tool')) continue;
      const answer = content.find(
        (item) => item.kind === 'text' && item.role === 'assistant' && item.isFinal,
      );
      if (answer) {
        answers.set(key, {
          answerId: answer.id,
          completed: turns.every((turn) => turn.status === 'completed'),
        });
      }
    }
    return answers;
  });
  protected rendererFor(type: string) {
    return this.artifactRenderers()[type] ?? null;
  }

  constructor() {
    registerChatIcons(this.iconRegistry, this.sanitizer);
    effect(() => this.synchronizeConversationState());
    afterEveryRender(() => this.flushPendingHistoryScroll());
    afterNextRender(() => this.observeHistoryContentResize());
  }

  private synchronizeConversationState(): void {
    this.turns();
    this.conversationStatus();
    untracked(() => {
      this.requestHistoryScroll();
      for (const [runKey, run] of this.detailRuns()) {
        const wasCompleted = this.initializedRuns.get(runKey);
        if (wasCompleted === true || wasCompleted === run.completed) continue;
        this.initializedRuns.set(runKey, run.completed);
        this.updateExpandedRuns(runKey, !run.completed);
      }
    });
  }

  private flushPendingHistoryScroll(): void {
    if (!this.historyScrollPending) return;
    this.historyScrollPending = false;
    this.alignHistoryWithComposer();
  }

  private observeHistoryContentResize(): void {
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (this.followingHistory) this.alignHistoryWithComposer();
    });
    observer.observe(this.historyContent().nativeElement);
    this.destroyRef.onDestroy(() => observer.disconnect());
  }

  private alignHistoryWithComposer(): void {
    const viewport = this.historyViewport()?.nativeElement;
    const composer = this.composer();
    if (!viewport || !composer) return;
    const target = Math.max(
      0,
      viewport.scrollTop +
        this.historyContent().nativeElement.getBoundingClientRect().bottom -
        composer.messageBoundaryTop(),
    );
    if (typeof viewport.scrollTo === 'function') {
      const reducedMotion = viewport.ownerDocument.defaultView?.matchMedia?.(
        '(prefers-reduced-motion: reduce)',
      ).matches;
      viewport.scrollTo({ top: target, behavior: reducedMotion ? 'auto' : 'smooth' });
    } else {
      viewport.scrollTop = target;
    }
  }

  protected stopFollowingHistory(): void {
    this.followingHistory = false;
  }

  protected requestHistoryScroll(): void {
    this.scrollAnchor.set(null);
    this.followingHistory = true;
    this.historyScrollPending = true;
  }

  protected detailsExpanded(turn: ChatTurn): boolean {
    return turn.runKey !== null && this.expandedRuns().has(turn.runKey);
  }

  protected detailsHidden(turn: ChatTurn): boolean {
    return (
      turn.runKey !== null && this.detailRuns().has(turn.runKey) && !this.detailsExpanded(turn)
    );
  }

  protected historyAnchorFor(turn: ChatTurn, item: ChatContent): string | null {
    if (item.kind === 'artifact') return JSON.stringify([turn.runKey, item.id]);
    return turn.runKey !== null &&
      this.detailRuns().has(turn.runKey) &&
      item.kind === 'text' &&
      item.role === 'assistant' &&
      item.isFinal
      ? JSON.stringify([turn.runKey, item.id])
      : null;
  }

  private selectScrollAnchor(anchor: string | null): boolean {
    const anchors =
      this.historyViewport()?.nativeElement.querySelectorAll<HTMLElement>('[data-scroll-anchor]');
    const hasAnchor =
      anchor !== null &&
      [...(anchors ?? [])].some((element) => element.getAttribute('data-scroll-anchor') === anchor);
    this.scrollAnchor.set(anchor);
    return hasAnchor;
  }

  protected anchorArtifact(anchor: string | null): void {
    this.stopFollowingHistory();
    this.historyScrollPending = !this.selectScrollAnchor(anchor);
  }

  protected setDetailsExpanded(runKey: string | null, expanded: boolean, messageId?: string): void {
    this.stopFollowingHistory();
    if (runKey === null) return;
    const answerId = messageId ?? this.detailRuns().get(runKey)?.answerId;
    if (answerId === undefined) return;
    const anchor = JSON.stringify([runKey, answerId]);
    const hasAnchor = this.selectScrollAnchor(anchor);
    if (!hasAnchor) this.historyScrollPending = true;
    else if (this.expandedRuns().has(runKey) !== expanded) this.historyScrollPending = false;
    this.updateExpandedRuns(runKey, expanded);
  }

  private updateExpandedRuns(runKey: string, expanded: boolean): void {
    this.expandedRuns.update((runs) => {
      if (runs.has(runKey) === expanded) return runs;
      const next = new Set(runs);
      if (expanded) next.add(runKey);
      else next.delete(runKey);
      return next;
    });
  }
}
