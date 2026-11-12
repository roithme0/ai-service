import {
  Component,
  effect,
  inject,
  input,
  OnDestroy,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
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
export interface ImageGenerationActionError {
  operation: 'submit' | 'recover' | 'reconnect' | 'primaryAction';
  message: string;
}

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
  readonly imageResult = inject(ImageResultService);
  readonly workflow = inject(ImageGenerationWorkflowService);
  readonly actionCoordinator = inject(ImageGenerationActionCoordinator);

  readonly state = input.required<Readonly<ImageGenerationState>>();
  readonly actions = input.required<ImageGenerationActions>();
  readonly primaryAction = input<ImageGenerationPrimaryAction>();
  readonly instructionMode = input<ImageGenerationInstructionMode>('editable');
  readonly actionError = output<ImageGenerationActionError>();

  private readonly inputPanel = viewChild(ImageGenerationInputPanelComponent);
  private readonly generatingPanel = viewChild(ImageGenerationGeneratingPanelComponent);
  private readonly outcomePanel = viewChild(ImageGenerationOutcomePanelComponent);

  readonly effectiveMode = signal<ImageGenerationInstructionMode>('editable');
  readonly error = signal<string | null>(null);
  readonly submissionUnknown = signal(false);
  private initialMode: ImageGenerationInstructionMode | null = null;
  private unknownBaseline: Readonly<ImageGenerationState> | null = null;
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
    if (this.submissionUnknown() && this.resolvesUnknown(state)) {
      this.submissionUnknown.set(false);
      this.unknownBaseline = null;
    }
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

  private resolvesUnknown(state: Readonly<ImageGenerationState>): boolean {
    const baseline = this.unknownBaseline;
    if (!baseline || state.instructions !== this.workflow.submitted()) return false;
    if (state.snapshot && state.snapshot.generation_id !== baseline.snapshot?.generation_id)
      return true;
    return (
      (state.admission === 'uncertain' || state.admission === 'rejected') &&
      (state.admission !== baseline.admission || state.instructions !== baseline.instructions)
    );
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
    const previousState = this.state();
    await this.invoke(
      () => this.actions().submit(text),
      'submit',
      'Der Status der Anfrage konnte nicht bestätigt werden.',
      text,
      previousState,
    );
  }

  async retry(): Promise<void> {
    if (this.actionCoordinator.pending()) return;
    const text = this.workflow.submitted();
    this.clearResult();
    this.workflow.startSubmission(text);
    this.focus('heading');
    const previousState = this.state();
    await this.invoke(
      () => this.actions().submit(text),
      'submit',
      'Der Status der Anfrage konnte nicht bestätigt werden.',
      text,
      previousState,
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
    operation: ImageGenerationActionError['operation'],
    message: string,
    submission?: string,
    previousState?: Readonly<ImageGenerationState>,
  ): Promise<void> {
    if (this.actionCoordinator.pending()) return;
    this.error.set(null);
    await this.actionCoordinator.invoke(
      action,
      () => {
        const state = this.state();
        const decisive =
          previousState &&
          state.instructions === submission &&
          (((state.admission === 'uncertain' || state.admission === 'rejected') &&
            (state.admission !== previousState.admission ||
              state.instructions !== previousState.instructions)) ||
            (state.snapshot !== null &&
              state.snapshot.generation_id !== previousState.snapshot?.generation_id));
        if (
          (operation === 'submit' && !decisive) ||
          (operation === 'recover' && state.admission === 'submitting')
        ) {
          this.unknownBaseline = { ...state };
          this.submissionUnknown.set(true);
        }
        this.actionError.emit({ operation, message });
      },
      submission,
    );
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
        this.actionError.emit({
          operation: 'primaryAction',
          message: 'Die Aktion ist fehlgeschlagen. Bitte versuchen Sie es erneut.',
        }),
    );
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.imageResult.clear();
    this.error.set(null);
  }
}
