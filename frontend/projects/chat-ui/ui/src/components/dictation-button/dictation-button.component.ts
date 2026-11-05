import {
  Component,
  computed,
  DestroyRef,
  effect,
  ElementRef,
  inject,
  input,
  output,
  signal,
  untracked,
  type Signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { isBrowserRecordingSupported, type RecordingState } from '@roithme0/chat-ui/recording';
import { TranscriptionError } from '@roithme0/chat-ui/transcription';
import type { DictationConfig, DictationError, DictationRecorder } from '../../dictation';
import { PreventPointerFocusDirective } from '../../directives/prevent-pointer-focus.directive';

export interface DictationEnvironment {
  readonly config: DictationConfig | null;
  readonly contextKey: string | null;
  readonly disabled: boolean;
  readonly editingDisabled: boolean;
}

interface DictationOperation {
  readonly config: DictationConfig;
  readonly contextKey: string | null;
  readonly abort: AbortController;
  phase: 'capture' | 'transcribing';
}

@Component({
  selector: 'ai-chat-dictation-button',
  imports: [MatButtonModule, MatIconModule, PreventPointerFocusDirective],
  templateUrl: './dictation-button.component.html',
  styleUrl: './dictation-button.component.scss',
})
export class DictationButtonComponent {
  // Read the live source to invalidate async work before Angular updates child bindings.
  readonly source = input.required<Signal<DictationEnvironment>>();
  readonly transcribed = output<string>();

  private readonly environment = computed(() => this.source()());
  private readonly operation = signal<DictationOperation | null>(null);
  readonly busy = computed(() => this.operation() !== null);
  protected readonly recordingState = signal<RecordingState>('ready');
  protected readonly visible = computed(
    () => this.environment().config !== null && isBrowserRecordingSupported(),
  );
  protected readonly buttonDisabled = computed(() => {
    const environment = this.environment();
    return (
      environment.editingDisabled ||
      (this.busy() ? this.recordingState() !== 'recording' : environment.disabled)
    );
  });

  private recorder: DictationRecorder | null = null;
  private recorderGeneration: object | null = null;

  constructor() {
    this.observeVisibility();
    inject(DestroyRef).onDestroy(() => this.cancel());
    effect(() => {
      this.environment();
      untracked(() => {
        const operation = this.operation();
        if (operation && !this.isCurrent(operation)) this.cancel();
      });
    });
  }

  protected toggle(): void {
    const operation = this.operation();
    if (operation) {
      if (!this.isCurrent(operation)) this.cancel();
      else {
        if (this.recordingState() === 'recording') this.recorder?.stop();
        return;
      }
    }
    const { config, contextKey, disabled, editingDisabled } = this.environment();
    if (!config || disabled || editingDisabled) return;
    const next: DictationOperation = {
      config,
      contextKey,
      abort: new AbortController(),
      phase: 'capture',
    };
    this.operation.set(next);
    void this.run(next);
  }

  private observeVisibility(): void {
    const document = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement.ownerDocument;
    const visibility = (): void => {
      if (document.hidden && this.operation()?.phase === 'capture') this.cancel();
    };
    document.addEventListener('visibilitychange', visibility);
    inject(DestroyRef).onDestroy(() =>
      document.removeEventListener('visibilitychange', visibility),
    );
  }

  private async run(operation: DictationOperation): Promise<void> {
    try {
      const recorder = this.createRecorder(operation);
      this.recorder = recorder;
      const result = await recorder.start();
      if (!this.isCurrent(operation)) return;
      this.releaseRecorder();
      if (result.kind === 'failed') {
        this.reportError(operation.config, { kind: 'recording', reason: result.error });
      } else if (result.kind === 'recorded') {
        operation.phase = 'transcribing';
        const text = (
          await operation.config.transcribe(result.recording, operation.abort.signal)
        ).trim();
        if (this.isCurrent(operation) && text !== '') this.transcribed.emit(text);
      }
    } catch (error: unknown) {
      if (this.isCurrent(operation)) {
        this.reportError(
          operation.config,
          operation.phase === 'capture'
            ? { kind: 'recording', reason: 'recorder-failed' }
            : {
                kind: 'transcription',
                reason: error instanceof TranscriptionError ? error.kind : 'invalid_response',
              },
        );
      }
    } finally {
      if (this.operation() === operation) {
        this.operation.set(null);
        this.releaseRecorder();
      }
    }
  }

  private isCurrent(operation: DictationOperation): boolean {
    const environment = this.environment();
    return (
      this.operation() === operation &&
      !operation.abort.signal.aborted &&
      !environment.editingDisabled &&
      environment.config === operation.config &&
      environment.contextKey === operation.contextKey
    );
  }

  private reportError(config: DictationConfig, error: DictationError): void {
    try {
      config.onError(error);
    } catch (callbackError: unknown) {
      if (typeof globalThis.reportError === 'function') globalThis.reportError(callbackError);
    }
  }

  private cancel(): void {
    const operation = this.operation();
    if (!operation) return;
    this.operation.set(null);
    operation.abort.abort();
    this.recorder?.cancel();
    this.releaseRecorder();
  }

  private releaseRecorder(): void {
    const recorder = this.recorder;
    this.recorder = null;
    this.recorderGeneration = null;
    this.recordingState.set('ready');
    recorder?.dispose();
  }
}
