import {
  Component,
  ElementRef,
  afterEveryRender,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';
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
  private readonly composer = viewChild.required<ElementRef<HTMLTextAreaElement>>('composer');
  private readonly document = inject(DOCUMENT);
  private restoreComposerFocus = false;
  private initialFocusPending = true;

  readonly disabled = input(false);
  readonly focusOnReady = input(false);
  readonly placeholder = input('Nachricht schreiben');
  readonly messageSubmitted = output<ChatSubmission>();
  protected readonly draft = signal('');

  constructor() {
    effect((onCleanup) => {
      if (!this.disabled()) return;
      const textarea = this.composer().nativeElement;
      this.restoreComposerFocus = this.document.activeElement === textarea;
      if (
        this.document.activeElement !== this.document.body &&
        this.document.activeElement !== textarea
      ) {
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
      if (this.disabled()) return;
      const shouldFocus =
        this.restoreComposerFocus || (this.focusOnReady() && this.initialFocusPending);
      this.restoreComposerFocus = false;
      this.initialFocusPending = false;
      if (!shouldFocus) return;
      const activeElement = this.document.activeElement;
      if (activeElement === this.document.body || activeElement === this.composer().nativeElement) {
        this.composer().nativeElement.focus({ preventScroll: true });
      }
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
    if (this.disabled()) {
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
