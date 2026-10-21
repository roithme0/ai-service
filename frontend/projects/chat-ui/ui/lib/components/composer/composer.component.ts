import { Component, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TextFieldModule } from '@angular/cdk/text-field';
import type { ChatSubmission } from '../../models/chat-message';

@Component({
  selector: 'ai-chat-composer',
  imports: [MatButtonModule, MatIconModule, TextFieldModule],
  templateUrl: './composer.component.html',
  styleUrl: './composer.component.scss',
})
export class ComposerComponent {
  readonly disabled = input(false);
  readonly editingDisabled = input(false);
  readonly placeholder = input('Nachricht schreiben');
  readonly mascotSource = input.required<string>();
  readonly messageSubmitted = output<ChatSubmission>();
  protected readonly draft = signal('');

  protected preventBlockedEdit(event: InputEvent): void {
    if (this.editingDisabled() && event.cancelable) {
      event.preventDefault();
    }
  }

  protected updateDraft(textarea: HTMLTextAreaElement): void {
    if (this.editingDisabled()) {
      textarea.value = this.draft();
      return;
    }
    this.draft.set(textarea.value);
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
    if (this.disabled() || this.editingDisabled()) {
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
      },
    });
  }
}
