import type { ChatConversationStatus, ChatTurn } from '@roithme0/chat-ui/ui';
import type {
  PresentedSession,
  PresentedTurn,
  SessionCreationRequest,
} from '../generated/native/types.gen';
import { SessionHttpError, type SessionTransport } from './session-transport';
import {
  presentSession,
  presentSessionArtifact,
  type SessionArtifactMapper,
} from './session-presentation';

export interface SessionViewState {
  readonly snapshot: PresentedSession | null;
  readonly turns: readonly ChatTurn[];
  readonly admission: 'idle' | 'pending' | 'accepted' | 'rejected' | 'uncertain';
  readonly observation: 'connecting' | 'connected' | 'lost';
  readonly composerDisabled: boolean;
  readonly composerEditingDisabled: boolean;
  readonly status: ChatConversationStatus | null;
}

export class SessionController {
  private epoch = 0;
  private observer: AbortController | null = null;
  private sessionId: string | null = null;
  private initialization: SessionCreationRequest | undefined;
  private sessionUnavailable = false;
  private admissionAction: ChatConversationStatus['action'];
  private awaitingLifecycle = false;
  private loadingPromptBaseline = 0;
  private admissionLifecycle: string | null = null;
  private admissionError: string | null = null;
  private sessionFailure: string | null = null;
  private value: SessionViewState = initialState();

  constructor(
    private readonly transport: SessionTransport,
    private readonly publish: (state: SessionViewState) => void,
    private readonly mapArtifact: SessionArtifactMapper = presentSessionArtifact,
  ) {}

  get state(): SessionViewState {
    return this.value;
  }

  async start(initialization?: SessionCreationRequest): Promise<void> {
    this.dispose();
    this.initialization = initialization;
    const epoch = this.epoch;
    this.value = initialState();
    this.publish(this.value);
    if (epoch !== this.epoch) return;
    try {
      const created = await this.transport.createSession(initialization);
      if (epoch !== this.epoch) return;
      this.sessionId = created.session_id;
      const observer = new AbortController();
      this.observer = observer;
      void this.observe(created.session_id, observer, epoch);
    } catch {
      if (epoch !== this.epoch) return;
      this.value = {
        ...this.value,
        observation: 'lost',
        status: {
          ...errorStatus('Die Unterhaltung konnte nicht gestartet werden.'),
          action: { id: 'new-session', label: 'Erneut versuchen' },
        },
      };
      this.publish(this.value);
    }
  }

  async submit(text: string, acknowledge: () => void): Promise<void> {
    const sessionId = this.sessionId;
    if (sessionId === null || this.value.composerDisabled) return;
    const epoch = this.epoch;

    this.beginAdmission();
    if (epoch !== this.epoch) return;

    try {
      await this.transport.submitPrompt(sessionId, text);
      if (epoch !== this.epoch) return;
      this.value = { ...this.value, admission: 'accepted' };
      this.update();
      if (epoch === this.epoch) acknowledge();
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      this.handleAdmissionFailure(error);
    }
  }

  async performAction(actionId: string): Promise<void> {
    if (actionId === 'new-session') await this.start(this.initialization);
  }

  dispose(): void {
    this.epoch += 1;
    this.observer?.abort();
    this.observer = null;
    this.sessionId = null;
    this.awaitingLifecycle = false;
    this.admissionLifecycle = null;
    this.loadingPromptBaseline = 0;
    this.admissionError = null;
    this.admissionAction = undefined;
    this.sessionUnavailable = false;
    this.sessionFailure = null;
  }

  private beginAdmission(): void {
    this.admissionLifecycle = lifecycleSignature(this.value.snapshot);
    this.loadingPromptBaseline = promptFragmentCount(this.value.snapshot);
    this.awaitingLifecycle = true;
    this.admissionError = null;
    this.value = { ...this.value, admission: 'pending' };
    this.update();
  }

  private handleAdmissionFailure(error: unknown): void {
    if (error instanceof SessionHttpError) {
      this.rejectAdmission(error);
    } else {
      this.value = { ...this.value, admission: 'uncertain' };
      this.admissionError =
        'Ob die Nachricht angenommen wurde, ist unbekannt. Weitere Nachrichten sind deaktiviert.';
    }
    this.update();
  }

  private rejectAdmission(error: SessionHttpError): void {
    this.awaitingLifecycle =
      error.kind === 'busy' && lifecycleSignature(this.value.snapshot) === this.admissionLifecycle;
    this.sessionUnavailable =
      error.kind === 'unknown' ||
      error.kind === 'unknown_configuration' ||
      error.kind === 'agent_unavailable';
    if (this.sessionUnavailable) {
      this.admissionAction = {
        id: 'new-session',
        label:
          error.kind === 'agent_unavailable' ? 'Erneut versuchen' : 'Neue Unterhaltung starten',
      };
    }
    this.value = { ...this.value, admission: 'rejected' };
    this.admissionError = admissionRejectionMessage(error.kind);
  }

  private async observe(
    sessionId: string,
    observer: AbortController,
    epoch: number,
  ): Promise<void> {
    try {
      for await (const event of this.transport.observeSession(sessionId, observer.signal)) {
        if (epoch !== this.epoch) return;
        if (event.kind === 'error') {
          if (event.reason === 'unknown') this.setUnavailable();
          break;
        }
        if (event.snapshot.session_id !== sessionId) break;
        this.value = { ...this.value, snapshot: event.snapshot, observation: 'connected' };
        if (lifecycleSignature(event.snapshot) !== this.admissionLifecycle)
          this.awaitingLifecycle = false;
        this.update();
      }
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (
        error instanceof SessionHttpError &&
        (error.kind === 'unknown' ||
          error.kind === 'unknown_configuration' ||
          error.kind === 'agent_unavailable')
      )
        this.setUnavailable(error.kind === 'agent_unavailable');
    } finally {
      observer.abort();
      if (this.observer === observer) this.observer = null;
    }
    if (epoch !== this.epoch) return;
    this.value = { ...this.value, observation: 'lost' };
    this.update();
  }

  private setUnavailable(agentUnavailable = false): void {
    this.sessionUnavailable = true;
    this.sessionFailure = agentUnavailable
      ? 'Der KI-Agent ist derzeit nicht verf\u00fcgbar.'
      : 'Diese Unterhaltung ist nicht mehr verf\u00fcgbar.';
    this.admissionAction = {
      id: 'new-session',
      label: agentUnavailable ? 'Erneut versuchen' : 'Neue Unterhaltung starten',
    };
  }

  private update(): void {
    const snapshot = this.value.snapshot;
    const lost = this.value.observation === 'lost';
    const turns = snapshot === null ? [] : presentSession(snapshot, lost, this.mapArtifact);
    const running = this.hasRunningTurn();

    this.value = {
      ...this.value,
      turns,
      status: this.presentationStatus(turns, running),
      composerDisabled: this.isSubmissionBlocked(running),
      composerEditingDisabled: this.value.admission === 'pending',
    };
    this.publish(this.value);
  }

  private hasRunningTurn(): boolean {
    return (
      this.value.snapshot?.history.some(
        (item) => item.part_kind === 'turn' && item.lifecycle.status === 'running',
      ) ?? false
    );
  }

  private isSubmissionBlocked(running: boolean): boolean {
    return (
      this.sessionUnavailable ||
      this.value.observation !== 'connected' ||
      running ||
      this.awaitingLifecycle ||
      this.value.admission === 'pending' ||
      this.value.admission === 'uncertain'
    );
  }

  private presentationStatus(
    turns: readonly ChatTurn[],
    running: boolean,
  ): ChatConversationStatus | null {
    const snapshot = this.value.snapshot;
    const latestStatus = latestRunStatus(snapshot);
    const executionFailure = executionFailureMessage(latestStatus);

    if (this.admissionError !== null) {
      return errorStatus(
        combineErrorMessages(this.admissionError, this.sessionFailure, executionFailure),
        this.admissionAction,
      );
    }
    if (this.sessionFailure !== null) {
      return errorStatus(
        combineErrorMessages(this.sessionFailure, executionFailure),
        this.admissionAction,
      );
    }
    if (this.value.observation === 'lost') {
      return errorStatus(observationFailureMessage(running, executionFailure));
    }
    if (this.value.observation === 'connecting') {
      return {
        kind: 'loading',
        placement: 'conversation',
        message: 'Unterhaltung wird gestartet …',
      };
    }
    if (executionFailure !== null && !this.awaitingLifecycle) {
      const followUpHint =
        latestStatus === 'failed' ? ' Du kannst eine neue Nachricht senden.' : '';
      return errorStatus(executionFailure + followUpHint);
    }
    if (
      running &&
      promptFragmentCount(snapshot) > this.loadingPromptBaseline &&
      waitingForResponse(turns)
    ) {
      return { kind: 'loading', placement: 'assistant', message: 'Antwort wird erstellt …' };
    }
    return null;
  }
}

function latestRunStatus(
  snapshot: PresentedSession | null,
): PresentedTurn['lifecycle']['status'] | undefined {
  return snapshot?.history
    .slice()
    .reverse()
    .find((item) => item.part_kind === 'turn')?.lifecycle.status;
}

function executionFailureMessage(
  status: PresentedTurn['lifecycle']['status'] | undefined,
): string | null {
  switch (status) {
    case 'failed':
      return 'Die Antwort konnte nicht erstellt werden.';
    case 'cancelled':
      return 'Die Antwort wurde abgebrochen.';
    default:
      return null;
  }
}

function combineErrorMessages(...messages: readonly (string | null)[]): string {
  return messages.filter((message) => message !== null).join(' ');
}

function observationFailureMessage(running: boolean, executionFailure: string | null): string {
  if (running) return 'Die Verbindung zur Antwort wurde unterbrochen. Der Ausgang ist unbekannt.';
  return combineErrorMessages(
    executionFailure,
    'Die Verbindung zur Unterhaltung wurde unterbrochen.',
  );
}

function admissionRejectionMessage(kind: SessionHttpError['kind']): string {
  switch (kind) {
    case 'busy':
      return 'Der KI-Agent bearbeitet bereits eine Anfrage.';
    case 'agent_unavailable':
      return 'Der KI-Agent ist derzeit nicht verf\u00fcgbar.';
    case 'unknown':
    case 'unknown_configuration':
      return 'Diese Unterhaltung ist nicht mehr verf\u00fcgbar.';
    default:
      return 'Die Nachricht konnte nicht angenommen werden.';
  }
}

function initialState(): SessionViewState {
  return {
    snapshot: null,
    turns: [],
    admission: 'idle',
    observation: 'connecting',
    composerDisabled: true,
    composerEditingDisabled: false,
    status: {
      kind: 'loading',
      placement: 'conversation',
      message: 'Unterhaltung wird gestartet …',
    },
  };
}

function errorStatus(
  message: string,
  action?: ChatConversationStatus['action'],
): ChatConversationStatus {
  return {
    kind: 'error',
    placement: 'assistant',
    message,
    ...(action === undefined ? {} : { action }),
  };
}

function lifecycleSignature(snapshot: PresentedSession | null): string {
  return JSON.stringify(
    snapshot?.history.filter((item) => item.part_kind === 'turn').map((item) => item.lifecycle),
  );
}

function waitingForResponse(turns: readonly ChatTurn[]): boolean {
  const active = turns
    .slice()
    .reverse()
    .find((turn) => turn.status === 'active');
  if (!active) return false;
  const index = turns.findIndex((turn) => turn.runKey === active.runKey);
  return (
    index >= 0 && !turns.some((turn) => turn.runKey === active.runKey && turn.content.length > 0)
  );
}

function promptFragmentCount(snapshot: PresentedSession | null): number {
  return (
    snapshot?.history.reduce(
      (count, item) =>
        item.part_kind === 'user-prompt'
          ? count + (typeof item.content === 'string' ? 1 : item.content.length)
          : count,
      0,
    ) ?? 0
  );
}
