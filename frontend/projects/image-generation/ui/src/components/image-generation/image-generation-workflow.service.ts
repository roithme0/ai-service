import { computed, Injectable, signal } from '@angular/core';
import type { ImageGenerationState } from '@roithme0/image-generation/controller';
import {
  applyControllerState,
  editInstructions,
  initialWorkflow,
  returnToOutcome,
  startSubmission,
  updateDraft,
  type InstructionMode,
  type StateTransition,
} from './workflow';

@Injectable()
export class ImageGenerationWorkflowService {
  private readonly workflow = signal(initialWorkflow());

  readonly panel = computed(() => {
    const activity = this.workflow().activity;
    if (activity === 'editing') return 'input';
    if (activity === 'editing-generating') return 'generating';
    return activity;
  });
  readonly draft = computed(() => this.workflow().draft);
  readonly submitted = computed(() => this.workflow().submitted);
  readonly failure = computed(() => this.workflow().failure);

  initialize(mode: InstructionMode): void {
    if (mode === 'hidden')
      this.workflow.update((workflow) => ({ ...workflow, activity: 'generating' }));
  }

  applyState(
    state: Readonly<ImageGenerationState>,
    mode: InstructionMode,
    submittingInstructions: string | null,
  ): Omit<StateTransition, 'workflow'> {
    const { workflow, ...effects } = applyControllerState(
      this.workflow(),
      state,
      mode,
      submittingInstructions,
    );
    this.workflow.set(workflow);
    return effects;
  }

  updateDraft(draft: string): void {
    this.workflow.update((workflow) => updateDraft(workflow, draft));
  }

  startSubmission(text: string): void {
    this.workflow.update((workflow) => startSubmission(workflow, text));
  }

  editInstructions(failure: boolean): void {
    this.workflow.update((workflow) => editInstructions(workflow, failure));
  }

  returnToOutcome(): void {
    this.workflow.update(returnToOutcome);
  }
}
