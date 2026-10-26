import { Component, DestroyRef, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TextFieldModule } from '@angular/cdk/text-field';
import type { ChatSubmission } from '../../models/chat-message';
import { PreventPointerFocusDirective } from '../../directives/prevent-pointer-focus.directive';
import { UsageLineComponent } from '../usage-line/usage-line.component';
import type { ChatUsageSummary } from '../../models/chat-usage';

@Component({
  selector: 'ai-chat-composer',
  imports: [
    MatButtonModule,
    MatIconModule,
    TextFieldModule,
    PreventPointerFocusDirective,
    UsageLineComponent,
  ],
  templateUrl: './composer.component.html',
  styleUrl: './composer.component.scss',
})
export class ComposerComponent {
  readonly disabled = input(false);
  readonly editingDisabled = input(false);
  readonly placeholder = input('Nachricht schreiben');
  readonly mascotSource = input.required<string>();
  readonly usage = input<ChatUsageSummary | null>(null);
  readonly messageSubmitted = output<ChatSubmission>();
  readonly focused = output<void>();
  readonly viewportResized = output<void>();
  protected readonly draft = signal('');
  private stopViewportObservation: (() => void) | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopObservingViewport());
  }

  protected onFocus(textarea: HTMLTextAreaElement): void {
    this.stopObservingViewport();
    const viewport = textarea.ownerDocument.defaultView?.visualViewport;
    if (viewport) {
      const onResize = (): void => {
        if (textarea.ownerDocument.activeElement === textarea) {
          this.viewportResized.emit();
        }
      };
      viewport.addEventListener('resize', onResize);
      this.stopViewportObservation = () => viewport.removeEventListener('resize', onResize);
    }
    this.focused.emit();
  }

  protected stopObservingViewport(): void {
    this.stopViewportObservation?.();
    this.stopViewportObservation = null;
  }

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
