import { Component, effect, input, OnDestroy, signal, untracked, viewChild } from '@angular/core';
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
  readonly state = input.required<Readonly<ImageGenerationState>>();
  readonly actions = input.required<ImageGenerationActions>();
  readonly primaryAction = input<ImageGenerationPrimaryAction>();
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
  private destroyed = false;
  private requested: string | null = null;
  private editing = false;
  private hasDraft = false;
  private lastAdmission: string = 'idle';

  constructor() {
    effect(() => {
      const state = this.state();
      untracked(() => this.applyState(state));
    });
  }

  private applyState(state: Readonly<ImageGenerationState>): void {
    const snapshot = state.snapshot;
    if (
      state.admission === 'submitting' &&
      this.lastAdmission !== 'submitting' &&
      this.lastAdmission !== 'uncertain' &&
      this.generation !== null
    ) {
      this.clearResult();
      this.generation = null;
      this.editing = false;
    }
    this.lastAdmission = state.admission;
    if (snapshot && snapshot.generation_id !== this.generation) {
      this.clearResult();
      this.generation = snapshot.generation_id;
      this.editing = false;
      this.hasDraft = false;
      this.submitted.set(state.instructions ?? this.submitted());
    }
    if (state.admission === 'rejected') {
      this.draft.set(state.instructions ?? this.submitted());
      this.error.set(state.error ?? 'Request was rejected.');
      this.navigate('input', 'textarea');
    } else if (
      state.admission === 'submitting' ||
      state.admission === 'uncertain' ||
      snapshot?.status === 'running'
    ) {
      this.navigate('generating', 'heading');
    } else if (snapshot?.status === 'failed') {
      this.failure.set(snapshot.error.detail);
      this.navigate('outcome', 'heading');
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

  private clearResult(): void {
    this.epoch++;
    const previous = this.result();
    if (previous) URL.revokeObjectURL(previous.url);
    this.result.set(null);
    this.error.set(null);
    this.pending.set(false);
    this.requested = null;
    this.loading.set(false);
    this.contentError.set(null);
  }

  async submit(): Promise<void> {
    if (this.pending()) return;
    const text = this.draft();
    if (!text.trim() || [...text].length > 32000) {
      this.error.set('Enter instructions of at most 32,000 characters.');
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
    await this.invoke(() => this.actions().submit(text), 'Could not submit request.');
  }

  async invoke(action: () => void | Promise<void>, message: string): Promise<void> {
    if (this.pending()) return;
    this.pending.set(true);
    this.error.set(null);
    const epoch = this.epoch;
    try {
      await action();
    } catch {
      if (!this.destroyed && epoch === this.epoch) this.error.set(message);
    } finally {
      if (!this.destroyed && epoch === this.epoch) this.pending.set(false);
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
      if (!this.destroyed && epoch === this.epoch) this.contentError.set('Could not load image.');
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
    this.contentError.set('Could not display image.');
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
        this.error.set('Action failed. Please try again.');
    } finally {
      if (!this.destroyed && epoch === this.epoch) this.pending.set(false);
    }
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clearResult();
  }
}
