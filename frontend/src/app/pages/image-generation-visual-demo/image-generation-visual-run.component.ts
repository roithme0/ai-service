import { Component, inject, input, OnDestroy, OnInit, signal } from '@angular/core';
import {
  MatSnackBar,
  type MatSnackBarRef,
  type TextOnlySnackBar,
} from '@angular/material/snack-bar';
import {
  ImageGenerationController,
  type ImageGenerationState,
} from '@roithme0/image-generation/controller';
import {
  ImageGenerationUiComponent,
  type ImageGenerationActions,
  type ImageGenerationInstructionMode,
  type ImageGenerationPrimaryAction,
} from '@roithme0/image-generation/ui';
import {
  ImageGenerationVisualTransport,
  type ImageGenerationVisualScenario,
} from './image-generation-visual-transport';
import { IMAGE_GENERATION_VISUAL_TIMINGS as timings } from './image-generation-visual-timings';

export type DemoActionOutcome = 'success' | 'failure';

@Component({
  selector: 'app-image-generation-visual-run',
  imports: [ImageGenerationUiComponent],
  template:
    '<ai-image-generation [state]="state()" [actions]="actions" [primaryAction]="primaryAction" [instructionMode]="instructionMode()" />',
  styles:
    ':host { display: block; height: 100%; min-height: 0; } ai-image-generation { display: block; height: 100%; }',
})
export class ImageGenerationVisualRun implements OnInit, OnDestroy {
  readonly scenario = input.required<ImageGenerationVisualScenario>();
  readonly instructionMode = input.required<ImageGenerationInstructionMode>();
  readonly outcome = input.required<DemoActionOutcome>();
  private readonly snackBar = inject(MatSnackBar);
  private readonly abort = new AbortController();
  private feedback: MatSnackBarRef<TextOnlySnackBar> | null = null;
  private controller: ImageGenerationController | null = null;
  protected readonly state = signal<Readonly<ImageGenerationState>>({
    admission: 'idle',
    instructions: null,
    snapshot: null,
    observation: 'idle',
    content: 'idle',
    error: null,
  });
  private getController(): ImageGenerationController {
    return (this.controller ??= new ImageGenerationController(
      new ImageGenerationVisualTransport(this.scenario()),
      (state) => this.state.set(state),
    ));
  }
  protected readonly actions: ImageGenerationActions = {
    submit: (instructions) => this.getController().submit(instructions),
    recoverSubmission: () => this.getController().recoverSubmission(),
    reconnect: () => this.getController().reconnect(),
    loadContent: async () => ({
      ...(await this.getController().loadContent()),
      filename: 'demo-image.png',
    }),
  };
  protected readonly primaryAction: ImageGenerationPrimaryAction = {
    label: 'Bild verwenden',
    run: async () => {
      const outcome = this.outcome();
      await new Promise<void>((resolve, reject) => {
        const signal = this.abort.signal;
        if (signal.aborted) {
          reject(new DOMException('Aborted', 'AbortError'));
          return;
        }
        const timer = setTimeout(() => {
          signal.removeEventListener('abort', cancel);
          resolve();
        }, timings.primaryActionMs);
        function cancel(): void {
          clearTimeout(timer);
          signal.removeEventListener('abort', cancel);
          reject(new DOMException('Aborted', 'AbortError'));
        }
        signal.addEventListener('abort', cancel, { once: true });
      });
      if (this.abort.signal.aborted) return;
      if (outcome === 'failure') throw new Error('Demo action failed');
      this.feedback = this.snackBar.open('Bild wurde von der Demo empfangen', undefined, {
        duration: timings.snackbarVisibilityMs,
      });
    },
  };
  ngOnInit(): void {
    if (this.instructionMode() === 'hidden') {
      void this.getController().submit('Eine sonnige Landschaft mit Bergen und einem See.');
    }
  }
  dispose(): void {
    if (this.abort.signal.aborted) return;
    this.abort.abort();
    this.controller?.dispose();
    this.feedback?.dismiss();
  }
  ngOnDestroy(): void {
    this.dispose();
  }
}
