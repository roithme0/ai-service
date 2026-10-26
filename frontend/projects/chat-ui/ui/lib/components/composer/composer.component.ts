import {
  afterNextRender,
  afterRenderEffect,
  Component,
  DestroyRef,
  effect,
  ElementRef,
  inject,
  Injector,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { TextFieldModule } from '@angular/cdk/text-field';
import type { ChatSubmission } from '../../models/chat-message';
import { PreventPointerFocusDirective } from '../../directives/prevent-pointer-focus.directive';
import { UsageLineComponent } from '../usage-line/usage-line.component';
import type { ChatUsage } from '../../models/chat-usage';
import { UsagePanelComponent } from '../usage-panel/usage-panel.component';

@Component({
  selector: 'ai-chat-composer',
  imports: [
    MatButtonModule,
    MatIconModule,
    TextFieldModule,
    PreventPointerFocusDirective,
    UsageLineComponent,
    UsagePanelComponent,
  ],
  templateUrl: './composer.component.html',
  styleUrl: './composer.component.scss',
})
export class ComposerComponent {
  readonly disabled = input(false);
  readonly editingDisabled = input(false);
  readonly placeholder = input('Nachricht schreiben');
  readonly mascotSource = input.required<string>();
  readonly usage = input<ChatUsage | null>(null);

  readonly messageSubmitted = output<ChatSubmission>();
  readonly focused = output<void>();
  readonly viewportResized = output<void>();

  protected readonly draft = signal('');
  protected readonly usageExpanded = signal(false);

  private readonly injector = inject(Injector);

  private readonly usageToggle = viewChild<ElementRef<HTMLButtonElement>>('usageToggle');
  private readonly usagePanel = viewChild(UsagePanelComponent);
  private readonly panelContainer = viewChild<ElementRef<HTMLElement>>('panelContainer');
  private readonly form = viewChild.required<ElementRef<HTMLFormElement>>('form');

  private readonly measuredScrollClearance = signal(0);
  readonly scrollClearance = this.measuredScrollClearance.asReadonly();
  private stopViewportObservation: (() => void) | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopObservingViewport());
    effect(() => {
      if (this.usage() === null) this.usageExpanded.set(false);
    });
    afterRenderEffect((onCleanup) => {
      const panel = this.panelContainer()?.nativeElement;
      const form = this.form().nativeElement;
      const measure = (): void => {
        this.measuredScrollClearance.set(panel ? Math.max(0, form.offsetTop - panel.offsetTop) : 0);
      };
      measure();
      if (panel && typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(measure);
        observer.observe(panel);
        onCleanup(() => observer.disconnect());
      }
    });
  }

  messageBoundaryTop(): number {
    return this.form().nativeElement.getBoundingClientRect().top;
  }

  protected setUsageExpanded(expanded: boolean, event: MouseEvent | KeyboardEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.usageExpanded.set(expanded);
    if (event.type === 'keydown' || event.detail === 0) {
      this.focusUsageControlAfterRender();
    }
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

  private focusUsageControlAfterRender(): void {
    afterNextRender(
      () => {
        if (this.usageExpanded()) {
          this.usagePanel()?.focusCollapseButton();
        } else {
          this.usageToggle()?.nativeElement.focus({ preventScroll: true });
        }
      },
      { injector: this.injector },
    );
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
