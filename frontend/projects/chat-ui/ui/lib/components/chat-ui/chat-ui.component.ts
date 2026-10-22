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
  private readonly history = viewChild<ElementRef<HTMLElement>>('history');

  private scrollHistoryToBottom = false;
  protected readonly detailScrollAnchor = signal<string | null>(null);
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

  protected readonly detailRuns = computed(() => {
    const answers = new Map<
      string,
      { readonly answerId: string; readonly active: boolean; readonly completed: boolean }
    >();
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
          active: turns.some((turn) => turn.status === 'active'),
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
    const initializedRuns = new Set<string>();
    effect(() => {
      this.turns();
      this.conversationStatus();
      untracked(() => {
        this.requestHistoryScroll();
        for (const [runKey, run] of this.detailRuns()) {
          if (initializedRuns.has(runKey) || (!run.active && !run.completed)) continue;
          if (run.completed) initializedRuns.add(runKey);
          this.setDetailsExpanded(runKey, !run.completed);
        }
      });
    });
    afterEveryRender(() => {
      if (!this.scrollHistoryToBottom) return;
      this.scrollHistoryToBottom = false;
      const history = this.history()?.nativeElement;
      if (!history) return;
      if (typeof history.scrollTo === 'function') {
        history.scrollTo({ top: history.scrollHeight, behavior: 'smooth' });
      } else {
        history.scrollTop = history.scrollHeight;
      }
    });
  }

  protected requestHistoryScroll(): void {
    this.detailScrollAnchor.set(null);
    this.scrollHistoryToBottom = true;
  }

  protected detailsExpanded(turn: ChatTurn): boolean {
    return turn.runKey !== null && this.expandedRuns().has(turn.runKey);
  }

  protected detailsHidden(turn: ChatTurn): boolean {
    return (
      turn.runKey !== null &&
      this.detailRuns().get(turn.runKey)?.completed === true &&
      !this.detailsExpanded(turn)
    );
  }

  protected answerAnchorFor(turn: ChatTurn, item: ChatContent): string | null {
    return turn.runKey !== null && this.detailRuns().get(turn.runKey)?.answerId === item.id
      ? JSON.stringify([turn.runKey, item.id])
      : null;
  }

  protected setDetailsExpanded(runKey: string | null, expanded: boolean): void {
    if (runKey === null) return;
    const answerId = this.detailRuns().get(runKey)?.answerId;
    if (answerId === undefined) return;
    const anchor = JSON.stringify([runKey, answerId]);
    const anchors =
      this.history()?.nativeElement.querySelectorAll<HTMLElement>('[data-detail-anchor]');
    const hasAnchor = [...(anchors ?? [])].some(
      (element) => element.getAttribute('data-detail-anchor') === anchor,
    );
    this.detailScrollAnchor.set(anchor);
    if (!hasAnchor) this.scrollHistoryToBottom = true;
    else if (this.expandedRuns().has(runKey) !== expanded) this.scrollHistoryToBottom = false;
    this.expandedRuns.update((runs) => {
      if (runs.has(runKey) === expanded) return runs;
      const next = new Set(runs);
      if (expanded) next.add(runKey);
      else next.delete(runKey);
      return next;
    });
  }
}
