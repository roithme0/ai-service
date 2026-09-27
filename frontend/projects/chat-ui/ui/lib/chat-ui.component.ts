import { Component, ElementRef, inject, input, output, signal, viewChild } from '@angular/core';
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

  readonly bannerTitle = input.required<string>();
  readonly bannerDescription = input.required<string>();
  readonly content = input.required<readonly ChatContent[]>();
  readonly artifactRenderers = input<ChatArtifactRendererMap>({});
  readonly conversationStatus = input<ChatConversationStatus | null>(null);
  readonly composerDisabled = input(false);
  readonly composerPlaceholder = input('Nachricht schreiben');
  
  readonly messageSubmitted = output<ChatSubmission>();
  readonly statusActionTriggered = output<string>();

  protected readonly draft = signal('');
  protected readonly renderAssistantMarkdown = renderAssistantMarkdown;

  protected rendererFor(type: string) {
    return this.artifactRenderers()[type] ?? null;
  }

  constructor() {
    registerChatIcons(this.iconRegistry, this.sanitizer);
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
