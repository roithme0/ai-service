import type { ImageGenerationState } from '@roithme0/image-generation/controller';

export type Activity = 'input' | 'editing' | 'editing-generating' | 'generating' | 'outcome';

function isEditing(activity: Activity): boolean {
  return activity === 'editing' || activity === 'editing-generating';
}

function stopEditing(activity: Activity): Activity {
  if (activity === 'editing') return 'input';
  if (activity === 'editing-generating') return 'generating';
  return activity;
}
export type InstructionMode = 'editable' | 'hidden';

export interface Workflow {
  activity: Activity;
  draft: string;
  submitted: string;
  failure: string | null;
  retainedDraft: string | null;
  generation: string | null;
  lastAdmission: ImageGenerationState['admission'];
}

export function initialWorkflow(): Workflow {
  return {
    activity: 'input',
    draft: '',
    submitted: '',
    failure: null,
    retainedDraft: null,
    generation: null,
    lastAdmission: 'idle',
  };
}

export interface StateTransition {
  workflow: Workflow;
  clearResult: boolean;
  preserveAction: boolean;
  error: string | null | undefined;
  loadContent: boolean;
}

function updateAdmission(workflow: Workflow, state: Readonly<ImageGenerationState>): void {
  const { admission, instructions } = state;
  if (
    admission === 'rejected' &&
    workflow.lastAdmission === 'rejected' &&
    instructions !== null &&
    instructions !== workflow.submitted
  ) {
    workflow.activity = stopEditing(workflow.activity);
  }
  if ((admission === 'submitting' || admission === 'rejected') && instructions !== null) {
    workflow.submitted = instructions;
  }
}

function updateActivity(
  workflow: Workflow,
  state: Readonly<ImageGenerationState>,
  mode: InstructionMode,
): void {
  const { admission, snapshot } = state;
  const editing = isEditing(workflow.activity);
  if (admission === 'idle' && !snapshot) {
    if (mode === 'hidden') workflow.activity = editing ? 'editing-generating' : 'generating';
    else workflow.activity = editing ? 'editing' : 'input';
  } else if (admission === 'rejected') {
    if (!editing) workflow.activity = 'generating';
  } else if (
    admission === 'submitting' ||
    admission === 'uncertain' ||
    snapshot?.status === 'running'
  ) {
    workflow.activity = editing ? 'editing-generating' : 'generating';
  } else if (snapshot?.status === 'failed') {
    workflow.failure = snapshot.error.detail;
    if (!editing) workflow.activity = 'outcome';
  } else if (snapshot?.status === 'completed') {
    workflow.failure = null;
    if (!editing) workflow.activity = 'outcome';
  }
}

export function applyControllerState(
  current: Workflow,
  state: Readonly<ImageGenerationState>,
  mode: InstructionMode,
  submittingInstructions: string | null,
): StateTransition {
  const workflow = { ...current };
  const { admission, snapshot } = state;
  updateAdmission(workflow, state);

  const generationDisappeared = (admission === 'rejected' || admission === 'idle') && !snapshot;
  const newSubmission =
    admission === 'submitting' &&
    workflow.lastAdmission !== 'submitting' &&
    workflow.lastAdmission !== 'uncertain';
  let clearResult = workflow.generation !== null && (generationDisappeared || newSubmission);
  if (clearResult) {
    workflow.generation = null;
    workflow.activity = stopEditing(workflow.activity);
    if (generationDisappeared) workflow.failure = null;
  }
  if (newSubmission) workflow.activity = stopEditing(workflow.activity);
  workflow.lastAdmission = admission;

  let preserveAction = false;
  if (snapshot && snapshot.generation_id !== workflow.generation) {
    preserveAction =
      !clearResult &&
      submittingInstructions !== null &&
      state.instructions === submittingInstructions;
    clearResult = true;
    workflow.generation = snapshot.generation_id;
    workflow.activity = stopEditing(workflow.activity);
    workflow.retainedDraft = null;
    workflow.submitted = state.instructions ?? workflow.submitted;
  }

  updateActivity(workflow, state, mode);
  return {
    workflow,
    clearResult,
    preserveAction,
    error:
      admission === 'rejected'
        ? (state.error ?? 'Die Anfrage wurde abgelehnt.')
        : clearResult
          ? null
          : undefined,
    loadContent:
      snapshot?.status === 'completed' &&
      admission !== 'rejected' &&
      admission !== 'submitting' &&
      admission !== 'uncertain',
  };
}

export function startSubmission(current: Workflow, text: string): Workflow {
  return {
    ...current,
    activity: 'generating',
    submitted: text,
    generation: null,
    retainedDraft: null,
    failure: null,
  };
}

export function editInstructions(current: Workflow, failure: boolean): Workflow {
  const draft = failure ? current.submitted : (current.retainedDraft ?? current.submitted);
  return { ...current, activity: 'editing', draft, retainedDraft: draft };
}

export function updateDraft(current: Workflow, draft: string): Workflow {
  return { ...current, draft, retainedDraft: current.retainedDraft === null ? null : draft };
}

export function returnToOutcome(current: Workflow): Workflow {
  return { ...current, activity: 'outcome' };
}
