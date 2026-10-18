import type {
  ChatArtifact,
  ChatContent,
  ChatConversationStatus,
  ChatTurn,
} from '@roithme0/chat-ui/ui';
import {
  ConversationApiError,
  ConversationNetworkError,
  type ApiErrorKind,
  type ApiMessage,
  type ConversationTransport,
} from './conversation-api';
import type {
  PublishedArtifactDictStrObject as ArtifactResponse,
  SessionSnapshotResponse,
} from '../generated/types.gen';

import { presentArtifact } from './generic-artifact-mapper';
import { itemIdentity, validateSnapshot } from './conversation-timeline';

export type ArtifactMapper = (artifact: ArtifactResponse) => ChatArtifact | null;

export interface ConversationViewState {
  readonly turns: readonly ChatTurn[];
  readonly composerDisabled: boolean;
  readonly status: ChatConversationStatus | null;
}

type ApiTurn = SessionSnapshotResponse['turns'][number];
type RetainedTurn = Readonly<Omit<ApiTurn, 'status' | 'timeline'>> & {
  readonly status: ApiTurn['status'] | 'unknown';
  readonly timeline: readonly ApiTurn['timeline'][number][];
};

interface PresentedTurns {
  readonly turns: readonly ChatTurn[];
  readonly responseTurnIds: ReadonlySet<string>;
}

const INITIAL_STATE: ConversationViewState = {
  turns: [],
  composerDisabled: true,
  status: loading('Unterhaltung wird gestartet …', 'conversation'),
};

export class ConversationController {
  private currentTurnId: string | null = null;
  private sessionId: string | null = null;
  private stateValue = INITIAL_STATE;
  private turns: readonly RetainedTurn[] = [];
  private epoch = 0;
  private observation: AbortController | null = null;

  constructor(
    private readonly transport: ConversationTransport,
    private readonly publish: (state: ConversationViewState) => void,
    private readonly mapArtifact: ArtifactMapper = presentArtifact,
  ) {}

  get state(): ConversationViewState {
    return this.stateValue;
  }

  dispose(): void {
    this.epoch += 1;
    this.observation?.abort();
    this.observation = null;
    this.sessionId = null;
    this.currentTurnId = null;
  }

  async start(): Promise<void> {
    this.dispose();
    const epoch = this.epoch;
    this.updateState({
      composerDisabled: true,
      status: loading('Unterhaltung wird gestartet …', 'conversation'),
    });
    try {
      const created = await this.transport.createSession();
      if (epoch !== this.epoch) return;
      this.sessionId = created.session_id;
      this.setTurns([]);
      this.updateState({ composerDisabled: false, status: null });
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (isUnsupportedApiRequest(error)) {
        this.setUnsupportedApiRequest(error);
        return;
      }
      this.updateState({
        composerDisabled: true,
        status: failure(
          messageFor(error, 'Die Unterhaltung konnte nicht gestartet werden.'),
          'conversation',
          'new-session',
          'Erneut versuchen',
        ),
      });
    }
  }

  async submit(text: string, acknowledge: () => void): Promise<void> {
    const sessionId = this.sessionId;
    if (sessionId === null || this.stateValue.composerDisabled) return;
    this.currentTurnId = null;
    const previousTurns = this.turns;
    const epoch = this.epoch;
    this.updateState({
      composerDisabled: true,
      status: null,
    });
    try {
      const accepted = await this.transport.appendMessage(sessionId, text);
      if (epoch !== this.epoch) return;
      this.acceptMessage(accepted, acknowledge);
      if (epoch !== this.epoch) return;
      await this.generate(sessionId);
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (error instanceof ConversationNetworkError) {
        await this.reconcileAppend(sessionId, previousTurns, text, acknowledge);
        return;
      }
      this.handleAppendFailure(error);
    }
  }

  async performAction(actionId: string): Promise<void> {
    if (actionId === 'new-session') {
      await this.start();
    }
  }

  private acceptMessage(message: ApiMessage, acknowledge: () => void): void {
    const epoch = this.epoch;
    const userMessageId = `confirmed-${this.turns.length}-user`;
    this.currentTurnId = message.turn_id;
    this.setTurns([
      ...this.turns,
      {
        turn_id: message.turn_id,
        user_message_id: userMessageId,
        status: 'pending',
        timeline: [{ kind: 'message', id: userMessageId, ...message }],
      },
    ]);
    this.updateState({
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    if (epoch === this.epoch) acknowledge();
  }

  private async generate(sessionId: string): Promise<void> {
    const epoch = this.epoch;
    this.updateState({
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    let turnId: string;
    let responseStarted = false;
    try {
      turnId = (await this.transport.generateTurn(sessionId)).turn_id;
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (error instanceof ConversationNetworkError || isKind(error, 'busy')) {
        try {
          const snapshot = await this.transport.readSession(sessionId);
          if (epoch !== this.epoch) return;
          validateSnapshot(snapshot, sessionId);
          const presented = this.setTurns(snapshot.turns);
          const turn = snapshot.turns.at(-1);
          this.currentTurnId = turn?.turn_id ?? null;
          responseStarted = turn !== undefined && presented.responseTurnIds.has(turn.turn_id);
          const terminal =
            turn !== undefined &&
            (turn.status === 'completed' ||
              turn.status === 'generation_failed' ||
              turn.status === 'conflict');
          this.updateState({
            composerDisabled: !terminal,
            status: terminal
              ? turn.status === 'completed'
                ? null
                : failure(
                    'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
                    'assistant',
                  )
              : turn?.status === 'closing' || responseStarted
                ? null
                : this.stateValue.status,
          });
          if (terminal) return;
          if (turn?.status === 'in_progress' || turn?.status === 'closing') {
            turnId = turn.turn_id;
          } else {
            this.observationLost();
            return;
          }
        } catch {
          if (epoch === this.epoch) this.observationLost();
          return;
        }
      } else {
        this.handleTurnFailure(error);
        return;
      }
    }
    if (epoch !== this.epoch) return;
    this.currentTurnId = turnId;
    const observation = new AbortController();
    this.observation = observation;
    const sequences = new Map<string, number>();
    let snapshotSequence = -1;
    let initialized = false;
    let latestSequence = -1;
    try {
      for await (const event of this.transport.observeTurn(sessionId, turnId, observation.signal)) {
        if (epoch !== this.epoch) return;
        if (event.turn_id !== turnId)
          throw new ConversationNetworkError('Ungültige Turn-Zuordnung.');
        if (event.kind === 'error') {
          if (event.reason === 'unavailable')
            this.handleTurnFailure(new ConversationApiError(410, 'expired'));
          else this.observationLost();
          return;
        }
        let presented: PresentedTurns;
        if (event.kind === 'snapshot') {
          if (initialized) throw new ConversationNetworkError('Ungültiger Anfangszustand.');
          validateSnapshot(event.snapshot, sessionId);
          if (!event.snapshot.turns.some((turn) => turn.turn_id === turnId))
            throw new ConversationNetworkError('Ungültige Turn-Zuordnung.');
          initialized = true;
          latestSequence = event.snapshot.sequence;
          presented = this.setTurns(event.snapshot.turns);
          snapshotSequence = event.snapshot.sequence;
          for (const turn of this.turns) {
            for (const item of turn.timeline) sequences.set(itemIdentity(item), snapshotSequence);
          }
        } else if (event.kind === 'upsert') {
          if (
            !initialized ||
            event.item.turn_id !== turnId ||
            event.identity !== itemIdentity(event.item)
          )
            throw new ConversationNetworkError('Ungültiger Timeline-Eintrag.');
          const turn = this.turns.find((turn) => turn.turn_id === turnId);
          if (turn === undefined) throw new ConversationNetworkError('Ungültige Turn-Zuordnung.');
          const position = turn.timeline.findIndex((item) => itemIdentity(item) === event.identity);
          if (
            (position !== -1 && event.order !== position) ||
            (position === -1 &&
              (event.order !== turn.timeline.length ||
                this.turns.some(
                  (other) =>
                    other.turn_id !== turnId &&
                    other.timeline.some((item) => itemIdentity(item) === event.identity),
                )))
          )
            throw new ConversationNetworkError('Ungültige Reihenfolge.');
          if (event.item.kind === 'artifact' && event.item.artifact.turn_id !== turnId)
            throw new ConversationNetworkError('Ungültiges Artefakt.');
          if (event.sequence <= (sequences.get(event.identity) ?? snapshotSequence)) continue;
          latestSequence = Math.max(latestSequence, event.sequence);
          sequences.set(event.identity, event.sequence);
          const timeline = [...turn.timeline];
          if (position === -1) timeline.push(event.item);
          else timeline[position] = event.item;
          presented = this.setTurns(
            this.turns.map((current) => (current === turn ? { ...turn, timeline } : current)),
          );
        } else if (event.kind === 'closing') {
          if (!initialized || event.sequence < latestSequence)
            throw new ConversationNetworkError('Ungültiger Abschlusszustand.');
          latestSequence = event.sequence;
          presented = this.updateCurrentTurnStatus('closing');
        } else {
          if (!initialized || event.sequence < latestSequence)
            throw new ConversationNetworkError('Ungültiger Endzustand.');
          this.updateCurrentTurnStatus(event.outcome);
          const failed = event.outcome !== 'completed';
          this.updateState({
            composerDisabled: false,
            status: failed
              ? failure(
                  'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
                  'assistant',
                )
              : null,
          });
          return;
        }
        responseStarted ||= presented.responseTurnIds.has(turnId);
        this.updateState({
          composerDisabled: true,
          status:
            this.turns.find((turn) => turn.turn_id === turnId)?.status === 'closing' ||
            responseStarted
              ? null
              : loading('Antwort wird erstellt …', 'assistant'),
        });
      }
      if (epoch === this.epoch) this.observationLost();
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (error instanceof ConversationApiError) this.handleTurnFailure(error);
      else this.observationLost();
    } finally {
      observation.abort();
      if (this.observation === observation) this.observation = null;
    }
  }

  private updateCurrentTurnStatus(status: RetainedTurn['status']): PresentedTurns {
    return this.setTurns(
      this.turns.map((turn) =>
        turn.turn_id !== this.currentTurnId ||
        (status === 'unknown' &&
          (turn.status === 'completed' ||
            turn.status === 'generation_failed' ||
            turn.status === 'conflict'))
          ? turn
          : { ...turn, status },
      ),
    );
  }

  private observationLost(): void {
    this.updateCurrentTurnStatus('unknown');
    this.updateState({
      composerDisabled: true,
      status: failure(
        'Die Verbindung zur Antwort wurde unterbrochen. Der Ausgang ist unbekannt.',
        'assistant',
      ),
    });
  }

  private async reconcileAppend(
    sessionId: string,
    previousTurns: readonly RetainedTurn[],
    text: string,
    acknowledge: () => void,
  ): Promise<void> {
    const epoch = this.epoch;
    try {
      const snapshot = await this.transport.readSession(sessionId);
      if (epoch !== this.epoch) return;
      validateSnapshot(snapshot, sessionId);
      const previousMessages = userMessages(previousTurns);
      const users = userMessages(snapshot.turns);
      const appended = users[previousMessages.length];
      this.setTurns(snapshot.turns);
      if (
        prefixMatches(previousMessages, users) &&
        appended?.role === 'user' &&
        appended.text === text
      ) {
        this.currentTurnId = appended.turn_id;
        this.updateState({
          composerDisabled: true,
          status: loading('Antwort wird erstellt …', 'assistant'),
        });
        if (epoch !== this.epoch) return;
        acknowledge();
        if (epoch !== this.epoch) return;
        await this.generate(sessionId);
        return;
      }
      this.updateState({
        composerDisabled: false,
        status: failure(
          'Die Nachricht konnte nicht gesendet werden. Bitte versuche es erneut.',
          'assistant',
        ),
      });
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (error instanceof ConversationApiError) this.handleAppendFailure(error);
      else this.observationLost();
    }
  }

  private handleAppendFailure(error: unknown): void {
    if (isUnsupportedApiRequest(error)) {
      this.setUnsupportedApiRequest(error);
      return;
    } else if (isKind(error, 'agent_unavailable')) {
      this.setAgentUnavailable();
      return;
    } else if (isTerminal(error)) {
      this.setTerminal(error);
      return;
    }
    this.updateState({
      composerDisabled: false,
      status: failure(
        messageFor(error, 'Die Nachricht konnte nicht gesendet werden. Bitte versuche es erneut.'),
        'assistant',
      ),
    });
  }

  private handleTurnFailure(error: unknown): void {
    this.updateCurrentTurnStatus(
      isKind(error, 'generation_failed') ? 'generation_failed' : 'unknown',
    );
    if (isUnsupportedApiRequest(error)) {
      this.setUnsupportedApiRequest(error);
    } else if (isTerminal(error)) {
      this.setTerminal(error);
    } else if (isKind(error, 'agent_unavailable')) {
      this.setAgentUnavailable();
    } else if (isKind(error, 'generation_failed')) {
      this.updateState({
        composerDisabled: false,
        status: failure(
          'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
          'assistant',
        ),
      });
    } else {
      this.updateState({
        composerDisabled: true,
        status: failure(
          messageFor(error, 'Die Antwort konnte nicht abgeglichen werden.'),
          'assistant',
        ),
      });
    }
  }

  private setAgentUnavailable(): void {
    this.updateState({
      composerDisabled: true,
      status: failure(
        'Der KI-Agent ist derzeit nicht verfügbar.',
        'conversation',
        'new-session',
        'Erneut versuchen',
      ),
    });
  }

  private setUnsupportedApiRequest(error: unknown): void {
    this.updateState({
      composerDisabled: true,
      status: failure(
        isKind(error, 'method_not_allowed')
          ? 'App und Backend sind nicht kompatibel.'
          : 'Der API-Endpunkt ist nicht verfügbar.',
        'conversation',
      ),
    });
  }

  private setTerminal(error: unknown): void {
    const exhausted = isKind(error, 'limit_reached');
    this.updateState({
      composerDisabled: true,
      status: failure(
        exhausted
          ? 'Diese Unterhaltung hat ihr Nachrichtenlimit erreicht.'
          : 'Diese Unterhaltung ist nicht mehr verfügbar.',
        'conversation',
        'new-session',
        'Neue Unterhaltung starten',
      ),
    });
  }

  private setTurns(turns: readonly RetainedTurn[]): PresentedTurns {
    const presented = presentTurns(turns, this.mapArtifact);
    this.turns = turns;
    this.stateValue = { ...this.stateValue, turns: presented.turns };
    return presented;
  }

  private updateState(state: Partial<Omit<ConversationViewState, 'turns'>>): void {
    this.stateValue = { ...this.stateValue, ...state };
    this.publish(this.stateValue);
  }
}

function presentTurns(turns: readonly RetainedTurn[], mapArtifact: ArtifactMapper): PresentedTurns {
  const responseTurnIds = new Set<string>();
  const presented = turns.map((turn): ChatTurn => ({
    id: turn.turn_id,
    userMessageId: turn.user_message_id,
    status:
      turn.status === 'unknown'
        ? 'unknown'
        : turn.status === 'completed'
          ? 'completed'
          : turn.status === 'generation_failed' || turn.status === 'conflict'
            ? 'failed'
            : 'active',
    content: turn.timeline.flatMap((item): ChatContent[] => {
      if (item.kind !== 'artifact' && (item.kind !== 'message' || item.role === 'assistant')) {
        responseTurnIds.add(item.turn_id);
      }
      switch (item.kind) {
        case 'message':
          return [
            { kind: 'text', id: item.id, role: item.role, text: item.text, turnId: item.turn_id },
          ];
        case 'intermediate':
          return [{ kind: 'intermediate', id: item.id, text: item.text, turnId: item.turn_id }];
        case 'tool':
          return [
            {
              kind: 'tool',
              id: itemIdentity(item),
              name: item.name,
              status: item.status,
              turnId: item.turn_id,
            },
          ];
        case 'artifact': {
          const artifact = mapArtifact(item.artifact);
          if (artifact !== null) responseTurnIds.add(item.turn_id);
          return artifact === null ? [] : [{ ...artifact, turnId: item.turn_id }];
        }
        case 'failure':
          return [
            {
              kind: 'failure',
              id: itemIdentity(item),
              turnId: item.turn_id,
              text: 'Die Antwort konnte nicht erstellt werden.',
            },
          ];
      }
    }),
  }));
  return { turns: presented, responseTurnIds };
}

function userMessages(turns: readonly RetainedTurn[]): readonly ApiMessage[] {
  return turns.flatMap((turn) =>
    turn.timeline.flatMap((item): ApiMessage[] =>
      item.kind === 'message' && item.role === 'user'
        ? [{ role: 'user', text: item.text, turn_id: item.turn_id }]
        : [],
    ),
  );
}

function prefixMatches(previous: readonly ApiMessage[], current: readonly ApiMessage[]): boolean {
  return previous.every(
    (message, index) =>
      current[index]?.role === message.role && current[index]?.text === message.text,
  );
}

function loading(
  message: string,
  placement: ChatConversationStatus['placement'],
): ChatConversationStatus {
  return { kind: 'loading', message, placement };
}

function failure(
  message: string,
  placement: ChatConversationStatus['placement'],
  id?: string,
  label?: string,
): ChatConversationStatus {
  return id === undefined || label === undefined
    ? { kind: 'error', message, placement }
    : { kind: 'error', message, placement, action: { id, label } };
}

function isKind(error: unknown, kind: ApiErrorKind): boolean {
  return error instanceof ConversationApiError && error.kind === kind;
}

function isUnsupportedApiRequest(error: unknown): boolean {
  return isKind(error, 'not_found') || isKind(error, 'method_not_allowed');
}

function isTerminal(error: unknown): boolean {
  return isKind(error, 'expired') || isKind(error, 'unknown') || isKind(error, 'limit_reached');
}

function messageFor(error: unknown, fallback: string): string {
  if (isKind(error, 'agent_unavailable')) return 'Der KI-Agent ist derzeit nicht verfügbar.';
  return error instanceof ConversationNetworkError ? error.message : fallback;
}
