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
import { DOCUMENT } from '@angular/common';
import { DomSanitizer } from '@angular/platform-browser';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule, MatIconRegistry } from '@angular/material/icon';
import { TextFieldModule } from '@angular/cdk/text-field';
import { renderAssistantMarkdown } from './assistant-markdown';
import { registerChatIcons } from './chat-icons';
import { ArtifactCardComponent } from './artifact-card.component';
import type {
  ChatArtifactRendererMap,
  ChatContent,
  ChatConversationStatus,
  ChatSubmission,
  ChatToolStatus,
} from './chat-message';

@Component({
  selector: 'ai-chat-ui',
  imports: [ArtifactCardComponent, MatButtonModule, MatIconModule, TextFieldModule],
  templateUrl: './chat-ui.component.html',
  styleUrl: './chat-ui.component.scss',
})
export class ChatUiComponent {
  private readonly iconRegistry = inject(MatIconRegistry);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly composer = viewChild.required<ElementRef<HTMLTextAreaElement>>('composer');
  private readonly history = viewChild.required<ElementRef<HTMLElement>>('history');
  private readonly document = inject(DOCUMENT);

  private restoreComposerFocus = false;
  private initialFocusPending = true;
  private scrollHistoryToBottom = false;

  readonly bannerTitle = input.required<string>();
  readonly bannerDescription = input.required<string>();
  readonly content = input.required<readonly ChatContent[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly composerDisabled = input(false);
  readonly focusOnReady = input(false);
  readonly composerPlaceholder = input('Nachricht schreiben');

  readonly messageSubmitted = output<ChatSubmission>();
  readonly statusActionTriggered = output<string>();

  protected readonly draft = signal('');
  protected readonly renderAssistantMarkdown = renderAssistantMarkdown;
  protected readonly toolStatusLabels: Record<ChatToolStatus, string> = {
    completed: 'Abgeschlossen',
    failed: 'Fehlgeschlagen',
    not_executed: 'Nicht ausgeführt',
    outcome_unknown: 'Ergebnis unklar',
  };
  private readonly revealedStatus = signal<ChatConversationStatus | null>(null);
  protected readonly statusVisible = computed(() => {
    const status = this.conversationStatus();
    return (
      status?.kind !== 'loading' || status.reveal !== 'delayed' || this.revealedStatus() === status
    );
  });

  protected rendererFor(type: string) {
    return this.artifactRenderers()[type] ?? null;
  }

  constructor() {
    registerChatIcons(this.iconRegistry, this.sanitizer);
    effect((onCleanup) => {
      if (!this.composerDisabled()) return;
      const textarea = this.composer().nativeElement;
      this.restoreComposerFocus = this.document.activeElement === textarea;
      if (this.document.activeElement !== this.document.body && this.document.activeElement !== textarea) {
        this.initialFocusPending = false;
      }
      const trackFocus = (event: FocusEvent): void => {
        if (event.target !== textarea) {
          this.restoreComposerFocus = false;
          this.initialFocusPending = false;
        }
      };
      this.document.addEventListener('focusin', trackFocus);
      onCleanup(() => this.document.removeEventListener('focusin', trackFocus));
    });
    afterEveryRender(() => {
      if (this.composerDisabled()) return;
      const shouldFocus = this.restoreComposerFocus || (this.focusOnReady() && this.initialFocusPending);
      this.restoreComposerFocus = false;
      this.initialFocusPending = false;
      if (!shouldFocus) return;
      const activeElement = this.document.activeElement;
      if (activeElement === this.document.body || activeElement === this.composer().nativeElement) {
        this.composer().nativeElement.focus({ preventScroll: true });
      }
    });
    effect(() => {
      this.content();
      this.conversationStatus();
      this.statusVisible();
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
    effect((onCleanup) => {
      const status = this.conversationStatus();
      this.revealedStatus.set(null);
      if (status?.kind !== 'loading' || status.reveal !== 'delayed') return;
      const timer = setTimeout(() => this.revealedStatus.set(status), 300);
      onCleanup(() => clearTimeout(timer));
    });
  }

  protected updateDraft(value: string): void {
    this.draft.set(value);
  }

  protected submit(event: Event): void {
    event.preventDefault();
    this.emitDraft();
  }

  protected submitFromKeyboard(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) {
      return;
    }

    event.preventDefault();
    this.emitDraft();
  }

  private emitDraft(): void {
    if (this.composerDisabled()) {
      return;
    }
    const normalizedText = this.draft().trim();
    if (normalizedText === '') {
      return;
    }

    this.messageSubmitted.emit({
      text: normalizedText,
      acknowledge: () => {
        if (this.draft().trim() === normalizedText) {
          this.draft.set('');
        }
        this.composer().nativeElement.focus();
      },
    });
  }
}
