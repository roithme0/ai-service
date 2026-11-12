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
import type { CompletedSnapshot } from '@roithme0/image-generation/controller';
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
type Result = ImageGenerationHandoff & { url: string };
export type ImageGenerationInstructionMode = 'editable' | 'hidden';
type Panel = 'input' | 'generating' | 'outcome';

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
})
export class ImageGenerationUiComponent implements OnDestroy {
  private readonly snackBar = inject(MatSnackBar);
  readonly state = input.required<Readonly<ImageGenerationState>>();
  readonly actions = input.required<ImageGenerationActions>();
  readonly primaryAction = input<ImageGenerationPrimaryAction>();
  readonly instructionMode = input<ImageGenerationInstructionMode>('editable');
  readonly effectiveMode = signal<ImageGenerationInstructionMode>('editable');
  private initialMode: ImageGenerationInstructionMode | null = null;
  private readonly inputPanel = viewChild(ImageGenerationInputPanelComponent);
  private readonly generatingPanel = viewChild(ImageGenerationGeneratingPanelComponent);
  private readonly outcomePanel = viewChild(ImageGenerationOutcomePanelComponent);
  readonly panel = signal<Panel>('input');
  readonly draft = signal('');
  readonly submitted = signal('');
  readonly result = signal<Result | null>(null);
  readonly failure = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly contentError = signal<string | null>(null);
  readonly pending = signal(false);
  readonly loading = signal(false);
  private generation: string | null = null;
  private epoch = 0;
  private actionEpoch = 0;
  private submittingInstructions: string | null = null;
  private destroyed = false;
  private requested: string | null = null;
  private editing = false;
  private hasDraft = false;
  private lastAdmission: string = 'idle';

  constructor() {
    effect(() => {
      const state = this.state();
      const mode = this.instructionMode();
      untracked(() => {
        if (this.initialMode === null) {
          this.initialMode = mode;
          this.effectiveMode.set(mode);
          if (mode === 'hidden') this.panel.set('generating');
        } else if (mode !== this.initialMode) {
          console.error('instructionMode cannot change after mounting.');
        }
        this.applyState(state);
      });
    });
  }

  private applyState(state: Readonly<ImageGenerationState>): void {
    const snapshot = state.snapshot;
    if (
      state.admission === 'rejected' &&
      this.lastAdmission === 'rejected' &&
      state.instructions !== null &&
      state.instructions !== this.submitted()
    ) {
      this.editing = false;
    }
    if (
      (state.admission === 'submitting' || state.admission === 'rejected') &&
      state.instructions !== null
    ) {
      this.submitted.set(state.instructions);
    }
    if (
      (state.admission === 'rejected' || state.admission === 'idle') &&
      this.generation !== null &&
      !snapshot
    ) {
      this.clearResult();
      this.generation = null;
      this.editing = false;
      this.failure.set(null);
    }
    if (
      state.admission === 'submitting' &&
      this.lastAdmission !== 'submitting' &&
      this.lastAdmission !== 'uncertain'
    ) {
      if (this.generation !== null) {
        this.clearResult();
        this.generation = null;
      }
      this.editing = false;
    }
    this.lastAdmission = state.admission;
    if (snapshot && snapshot.generation_id !== this.generation) {
      this.clearResult(
        this.submittingInstructions !== null && state.instructions === this.submittingInstructions,
      );
      this.generation = snapshot.generation_id;
      this.editing = false;
      this.hasDraft = false;
      this.submitted.set(state.instructions ?? this.submitted());
    }
    if (state.admission === 'idle' && !snapshot) {
      this.navigate(this.effectiveMode() === 'hidden' ? 'generating' : 'input', 'heading');
    } else if (state.admission === 'rejected') {
      this.error.set(state.error ?? 'Die Anfrage wurde abgelehnt.');
      if (!this.editing) this.navigate('generating', 'heading');
    } else if (
      state.admission === 'submitting' ||
      state.admission === 'uncertain' ||
      snapshot?.status === 'running'
    ) {
      this.navigate('generating', 'heading');
    } else if (snapshot?.status === 'failed') {
      this.failure.set(snapshot.error.detail);
      if (!this.editing) this.navigate('outcome', 'heading');
    } else if (snapshot?.status === 'completed') {
      this.failure.set(null);
      if (!this.editing) this.navigate('outcome', 'heading');
      if (this.requested !== snapshot.generation_id) void this.load(snapshot);
    }
  }

  private navigate(panel: Panel, target: 'heading' | 'textarea'): void {
    if (this.panel() !== panel) {
      this.panel.set(panel);
      this.focus(target);
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
    this.epoch++;
    if (!preserveAction) {
      this.actionEpoch++;
      this.submittingInstructions = null;
    }
    const previous = this.result();
    if (previous) URL.revokeObjectURL(previous.url);
    this.result.set(null);
    this.error.set(null);
    if (!preserveAction) this.pending.set(false);
    this.requested = null;
    this.loading.set(false);
    this.contentError.set(null);
  }

  async submit(): Promise<void> {
    if (this.pending()) return;
    const text = this.draft();
    if (!text.trim() || [...text].length > 32000) {
      this.error.set('Geben Sie eine Beschreibung mit höchstens 32.000 Zeichen ein.');
      this.focus('textarea');
      return;
    }
    this.clearResult();
    this.generation = null;
    this.submitted.set(text);
    this.editing = false;
    this.hasDraft = false;
    this.failure.set(null);
    this.error.set(null);
    this.panel.set('generating');
    this.focus('heading');
    this.submittingInstructions = text;
    await this.invoke(
      () => this.actions().submit(text),
      'Die Anfrage konnte nicht gesendet werden.',
      text,
    );
  }

  async retry(): Promise<void> {
    if (this.pending()) return;
    const text = this.submitted();
    this.clearResult();
    this.generation = null;
    this.editing = false;
    this.hasDraft = false;
    this.failure.set(null);
    this.panel.set('generating');
    this.focus('heading');
    this.submittingInstructions = text;
    await this.invoke(
      () => this.actions().submit(text),
      'Die Anfrage konnte nicht gesendet werden.',
      text,
    );
  }

  editFailure(): void {
    if (this.pending() || this.effectiveMode() === 'hidden') return;
    this.draft.set(this.submitted());
    this.hasDraft = true;
    this.editing = true;
    this.error.set(null);
    this.panel.set('input');
    this.focus('textarea');
  }

  async invoke(
    action: () => void | Promise<void>,
    message: string,
    submission?: string,
  ): Promise<void> {
    if (this.pending()) return;
    this.pending.set(true);
    this.error.set(null);
    const epoch = this.actionEpoch;
    try {
      await action();
    } catch {
      if (!this.destroyed && epoch === this.actionEpoch) this.error.set(message);
    } finally {
      if (submission !== undefined && epoch === this.actionEpoch)
        this.submittingInstructions = null;
      if (!this.destroyed && epoch === this.actionEpoch) this.pending.set(false);
    }
  }

  async load(snapshot: CompletedSnapshot): Promise<void> {
    if (this.loading()) return;
    this.requested = snapshot.generation_id;
    this.loading.set(true);
    this.contentError.set(null);
    const epoch = this.epoch;
    try {
      const content = await this.actions().loadContent();
      if (this.destroyed || epoch !== this.epoch) return;
      if (
        content.snapshot.generation_id !== snapshot.generation_id ||
        content.blob.type !== 'image/png' ||
        !content.blob.size
      )
        throw new Error('Invalid image content');
      const url = URL.createObjectURL(content.blob);
      this.result.set({ ...content, instructions: this.submitted(), url });
    } catch {
      if (!this.destroyed && epoch === this.epoch)
        this.contentError.set('Das Bild konnte nicht geladen werden.');
    } finally {
      if (!this.destroyed && epoch === this.epoch) this.loading.set(false);
    }
  }

  retryImage(): void {
    const snapshot = this.state().snapshot;
    if (snapshot?.status === 'completed') void this.load(snapshot);
  }

  imageError(): void {
    const result = this.result();
    if (result) URL.revokeObjectURL(result.url);
    this.result.set(null);
    this.contentError.set('Das Bild konnte nicht angezeigt werden.');
  }

  refine(): void {
    if (this.pending()) return;
    if (!this.hasDraft) this.draft.set(this.submitted());
    this.hasDraft = true;
    this.editing = true;
    this.error.set(null);
    this.panel.set('input');
    this.focus('textarea');
  }

  back(): void {
    if (!this.pending()) {
      this.editing = false;
      this.panel.set('outcome');
      this.focus('heading');
    }
  }

  download(): void {
    const result = this.result();
    if (!result || this.pending()) return;
    const anchor = document.createElement('a');
    anchor.href = result.url;
    anchor.download = result.filename;
    anchor.click();
  }

  async handoff(): Promise<void> {
    const result = this.result();
    const action = this.primaryAction();
    if (!result || !action || !action.label.trim() || this.pending()) return;
    const epoch = this.epoch;
    this.pending.set(true);
    this.error.set(null);
    try {
      await action.run({
        blob: result.blob,
        filename: result.filename,
        snapshot: result.snapshot,
        instructions: result.instructions,
      });
    } catch {
      if (!this.destroyed && epoch === this.epoch)
        this.snackBar.open('Die Aktion ist fehlgeschlagen. Bitte versuchen Sie es erneut.', 'OK', {
          duration: 6000,
          politeness: 'assertive',
        });
    } finally {
      if (!this.destroyed && epoch === this.epoch) this.pending.set(false);
    }
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clearResult();
  }
}
