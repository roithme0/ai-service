import {
  Component,
  effect,
  inject,
  input,
  OnDestroy,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import type { ImageContent, ImageGenerationState } from '@roithme0/image-generation/controller';
import { ImageResultService } from './image-result.service';
import { ImageGenerationActionCoordinator } from './image-generation-action-coordinator.service';
import { ImageGenerationWorkflowService } from './image-generation-workflow.service';
import { ImageGenerationInputPanelComponent } from '../input-panel/input-panel.component';
import { ImageGenerationGeneratingPanelComponent } from '../generating-panel/generating-panel.component';
import { ImageGenerationOutcomePanelComponent } from '../outcome-panel/outcome-panel.component';

export interface ImageGenerationActions {
  submit(instructions: string): Promise<void>;
  recoverSubmission(): Promise<void>;
  reconnect(): void | Promise<void>;
  loadContent(): Promise<ImageContent>;
}
export interface ImageGenerationHandoff extends ImageContent {
  instructions: string;
}
export interface ImageGenerationPrimaryAction {
  label: string;
  run(payload: ImageGenerationHandoff): Promise<void>;
}
export type ImageGenerationInstructionMode = 'editable' | 'hidden';

@Component({
  selector: 'ai-image-generation',
  standalone: true,
  imports: [
    ImageGenerationInputPanelComponent,
    ImageGenerationGeneratingPanelComponent,
    ImageGenerationOutcomePanelComponent,
  ],
  templateUrl: './image-generation.component.html',
  styleUrl: './image-generation.component.scss',
  providers: [ImageResultService, ImageGenerationWorkflowService, ImageGenerationActionCoordinator],
})
export class ImageGenerationUiComponent implements OnDestroy {
  private readonly snackBar = inject(MatSnackBar);
  readonly imageResult = inject(ImageResultService);
  readonly workflow = inject(ImageGenerationWorkflowService);
  readonly actionCoordinator = inject(ImageGenerationActionCoordinator);

  readonly state = input.required<Readonly<ImageGenerationState>>();
  readonly actions = input.required<ImageGenerationActions>();
  readonly primaryAction = input<ImageGenerationPrimaryAction>();
  readonly instructionMode = input<ImageGenerationInstructionMode>('editable');

  private readonly inputPanel = viewChild(ImageGenerationInputPanelComponent);
  private readonly generatingPanel = viewChild(ImageGenerationGeneratingPanelComponent);
  private readonly outcomePanel = viewChild(ImageGenerationOutcomePanelComponent);

  readonly effectiveMode = signal<ImageGenerationInstructionMode>('editable');
  readonly error = signal<string | null>(null);
  private initialMode: ImageGenerationInstructionMode | null = null;
  private destroyed = false;

  constructor() {
    effect(() => {
      const state = this.state();
      const mode = this.instructionMode();
      untracked(() => {
        if (this.initialMode === null) {
          this.initialMode = mode;
          this.effectiveMode.set(mode);
          this.workflow.initialize(mode);
        } else if (mode !== this.initialMode) {
          console.error('instructionMode cannot change after mounting.');
        }
        this.applyState(state);
      });
    });
  }

  private applyState(state: Readonly<ImageGenerationState>): void {
    const previousPanel = this.workflow.panel();
    const transition = this.workflow.applyState(
      state,
      this.effectiveMode(),
      this.actionCoordinator.submittingInstructions,
    );
    if (transition.clearResult) this.clearResult(transition.preserveAction);
    if (transition.error !== undefined) this.error.set(transition.error);
    if (previousPanel !== this.workflow.panel()) this.focus('heading');
    const snapshot = state.snapshot;
    if (
      transition.loadContent &&
      snapshot?.status === 'completed' &&
      !this.imageResult.hasRequested(snapshot.generation_id)
    ) {
      void this.imageResult.load(snapshot, this.workflow.submitted(), () =>
        this.actions().loadContent(),
      );
    }
  }

  private focus(target: 'heading' | 'textarea'): void {
    setTimeout(() => {
      if (this.destroyed) return;
      if (target === 'textarea') this.inputPanel()?.focusInstructions();
      else {
        const panel = this.inputPanel() ?? this.generatingPanel() ?? this.outcomePanel();
        panel?.focusHeading();
      }
    });
  }

  private clearResult(preserveAction = false): void {
    this.actionCoordinator.clearResult(preserveAction);
    this.imageResult.clear();
    this.error.set(null);
  }

  async submit(): Promise<void> {
    if (this.actionCoordinator.pending()) return;
    const text = this.workflow.draft();
    if (!text.trim() || [...text].length > 32000) {
      this.error.set('Geben Sie eine Beschreibung mit höchstens 32.000 Zeichen ein.');
      this.focus('textarea');
      return;
    }
    this.clearResult();
    this.workflow.startSubmission(text);
    this.error.set(null);
    this.focus('heading');
    await this.invoke(
      () => this.actions().submit(text),
      'Die Anfrage konnte nicht gesendet werden.',
      text,
    );
  }

  async retry(): Promise<void> {
    if (this.actionCoordinator.pending()) return;
    const text = this.workflow.submitted();
    this.clearResult();
    this.workflow.startSubmission(text);
    this.focus('heading');
    await this.invoke(
      () => this.actions().submit(text),
      'Die Anfrage konnte nicht gesendet werden.',
      text,
    );
  }

  editFailure(): void {
    if (this.actionCoordinator.pending() || this.effectiveMode() === 'hidden') return;
    this.workflow.editInstructions(true);
    this.error.set(null);
    this.focus('textarea');
  }

  async invoke(
    action: () => void | Promise<void>,
    message: string,
    submission?: string,
  ): Promise<void> {
    if (this.actionCoordinator.pending()) return;
    this.error.set(null);
    await this.actionCoordinator.invoke(action, () => this.error.set(message), submission);
  }

  retryImage(): void {
    const snapshot = this.state().snapshot;
    if (snapshot?.status === 'completed')
      void this.imageResult.load(snapshot, this.workflow.submitted(), () =>
        this.actions().loadContent(),
      );
  }

  refine(): void {
    if (this.actionCoordinator.pending()) return;
    this.workflow.editInstructions(false);
    this.error.set(null);
    this.focus('textarea');
  }

  back(): void {
    if (!this.actionCoordinator.pending()) {
      this.workflow.returnToOutcome();
      this.focus('heading');
    }
  }

  download(): void {
    const result = this.imageResult.result();
    if (!result || this.actionCoordinator.pending()) return;
    const anchor = document.createElement('a');
    anchor.href = result.url;
    anchor.download = result.filename;
    anchor.click();
  }

  async handoff(): Promise<void> {
    const result = this.imageResult.result();
    const action = this.primaryAction();
    if (!result || !action || !action.label.trim() || this.actionCoordinator.pending()) return;
    this.error.set(null);
    await this.actionCoordinator.handoff(
      () =>
        action.run({
          blob: result.blob,
          filename: result.filename,
          snapshot: result.snapshot,
          instructions: result.instructions,
        }),
      () =>
        this.snackBar.open('Die Aktion ist fehlgeschlagen. Bitte versuchen Sie es erneut.', 'OK', {
          duration: 6000,
          politeness: 'assertive',
        }),
    );
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.imageResult.clear();
    this.error.set(null);
  }
}
