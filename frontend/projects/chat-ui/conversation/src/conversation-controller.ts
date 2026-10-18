import type {
  ChatArtifact,
  ChatContent,
  ChatConversationStatus,
  ChatTextMessage,
  ChatTurn,
  ChatTurnStatus,
} from '@roithme0/chat-ui/ui';
import {
  ConversationApiError,
  ConversationNetworkError,
  type ApiErrorKind,
  type ApiMessage,
  type ConversationTransport,
} from './conversation-api';
import type { ArtifactResponse, SessionSnapshotResponse } from '../generated/types.gen';

import { presentArtifact } from './generic-artifact-mapper';

export type ArtifactMapper = (artifact: ArtifactResponse) => ChatArtifact | null;

export interface ConversationViewState {
  readonly content: readonly ChatContent[];
  readonly turns: readonly ChatTurn[];
  readonly composerDisabled: boolean;
  readonly status: ChatConversationStatus | null;
}

const INITIAL_STATE: ConversationViewState = {
  content: [],
  turns: [],
  composerDisabled: true,
  status: loading('Unterhaltung wird gestartet …', 'conversation'),
};

export class ConversationController {
  private currentTurnId: string | null = null;
  private sessionId: string | null = null;
  private stateValue = INITIAL_STATE;
  private epoch = 0;
  private observation: AbortController | null = null;
  private confirmedMessages: readonly ApiMessage[] = [];

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
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: loading('Unterhaltung wird gestartet …', 'conversation'),
    });
    try {
      const created = await this.transport.createSession();
      if (epoch !== this.epoch) return;
      this.confirmedMessages = [];
      this.sessionId = created.session_id;
      this.setState({ content: [], turns: [], composerDisabled: false, status: null });
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (isUnsupportedApiRequest(error)) {
        this.setUnsupportedApiRequest(error);
        return;
      }
      this.setState({
        ...this.stateValue,
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
    const previousMessages = this.confirmedMessages.filter((message) => message.role === 'user');
    const epoch = this.epoch;
    this.setState({
      ...this.stateValue,
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
        await this.reconcileAppend(sessionId, previousMessages, text, acknowledge);
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
    const userIndex = this.confirmedMessages.filter((item) => item.role === 'user').length;
    this.confirmedMessages = [...this.confirmedMessages, message];
    this.setState({
      ...this.stateValue,
      content: [...this.stateValue.content, presentMessage(message, userIndex)],
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    if (epoch === this.epoch) acknowledge();
  }

  private async generate(sessionId: string): Promise<void> {
    const epoch = this.epoch;
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    let turnId: string;
    let responseStarted = false;
    let closing = false;
    try {
      turnId = (await this.transport.generateTurn(sessionId)).turn_id;
    } catch (error: unknown) {
      if (epoch !== this.epoch) return;
      if (error instanceof ConversationNetworkError || isKind(error, 'busy')) {
        try {
          const snapshot = await this.transport.readSession(sessionId);
          if (epoch !== this.epoch) return;
          this.confirmedMessages = snapshot.messages;
          const presented = presentTimeline(
            snapshot.timeline,
            snapshot.artifacts,
            this.mapArtifact,
          );
          const turn = snapshot.turns.at(-1);
          this.currentTurnId = turn?.turn_id ?? null;
          responseStarted = turn !== undefined && presented.responseTurnIds.has(turn.turn_id);
          closing = turn?.status === 'closing';
          const terminal =
            turn !== undefined &&
            (turn.status === 'completed' ||
              turn.status === 'generation_failed' ||
              turn.status === 'conflict');
          this.setState({
            ...this.stateValue,
            content: presented.content,
            turns: snapshot.turns.map(presentTurn),
            composerDisabled: !terminal,
            status: terminal
              ? turn.status === 'completed'
                ? null
                : failure(
                    'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
                    'assistant',
                  )
              : closing || responseStarted
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
    const items = new Map<
      string,
      { order: number; sequence: number; item: SessionSnapshotResponse['timeline'][number] }
    >();
    const artifacts = new Map<string, ArtifactResponse>();
    let turns = this.stateValue.turns;
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
        if (event.kind === 'snapshot') {
          if (initialized || event.snapshot.session_id !== sessionId)
            throw new ConversationNetworkError('Ungültiger Anfangszustand.');
          initialized = true;
          closing = event.snapshot.turns.some(
            (turn) => turn.turn_id === turnId && turn.status === 'closing',
          );
          latestSequence = event.snapshot.sequence;
          this.confirmedMessages = event.snapshot.messages;
          turns = event.snapshot.turns.map(presentTurn);
          event.snapshot.artifacts.forEach((artifact) =>
            artifacts.set(artifact.artifact_id, artifact),
          );
          event.snapshot.timeline.forEach((item, order) =>
            items.set(itemIdentity(item), { item, order, sequence: event.snapshot.sequence }),
          );
        } else if (event.kind === 'upsert') {
          if (
            !initialized ||
            event.item.turn_id !== turnId ||
            event.identity !== itemIdentity(event.item)
          )
            throw new ConversationNetworkError('Ungültiger Timeline-Eintrag.');
          const previous = items.get(event.identity);
          if (previous !== undefined && event.sequence <= previous.sequence) continue;
          if (previous !== undefined && event.order !== previous.order)
            throw new ConversationNetworkError('Ungültige Reihenfolge.');
          if (event.item.kind === 'artifact') {
            if (
              event.artifact == null ||
              event.artifact.artifact_id !== event.item.artifact_id ||
              event.artifact.turn_id !== turnId
            )
              throw new ConversationNetworkError('Ungültiges Artefakt.');
            artifacts.set(event.artifact.artifact_id, event.artifact);
          } else if (event.artifact != null)
            throw new ConversationNetworkError('Unerwartetes Artefakt.');
          latestSequence = Math.max(latestSequence, event.sequence);
          items.set(event.identity, {
            item: event.item,
            order: event.order,
            sequence: event.sequence,
          });
        } else if (event.kind === 'closing') {
          if (!initialized || event.sequence < latestSequence)
            throw new ConversationNetworkError('Ungültiger Abschlusszustand.');
          latestSequence = event.sequence;
          closing = true;
        } else {
          if (!initialized || event.sequence < latestSequence)
            throw new ConversationNetworkError('Ungültiger Endzustand.');
          const failed = event.outcome !== 'completed';
          this.setState({
            ...this.stateValue,
            composerDisabled: false,
            turns: this.turnsWithCurrentStatus(failed ? 'failed' : 'completed'),
            status: failed
              ? failure(
                  'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
                  'assistant',
                )
              : null,
          });
          return;
        }
        const timeline = [...items.values()]
          .sort((a, b) => a.order - b.order)
          .map((entry) => entry.item);
        const presented = presentTimeline(timeline, [...artifacts.values()], this.mapArtifact);
        responseStarted ||= presented.responseTurnIds.has(turnId);
        this.setState({
          ...this.stateValue,
          content: presented.content,
          turns,
          composerDisabled: true,
          status:
            closing || responseStarted ? null : loading('Antwort wird erstellt …', 'assistant'),
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

  private turnsWithCurrentStatus(status: ChatTurnStatus): readonly ChatTurn[] {
    return this.stateValue.turns.map((turn) =>
      turn.id !== this.currentTurnId || (status === 'unknown' && turn.status !== 'active')
        ? turn
        : { ...turn, status },
    );
  }

  private observationLost(): void {
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      turns: this.turnsWithCurrentStatus('unknown'),
      status: failure(
        'Die Verbindung zur Antwort wurde unterbrochen. Der Ausgang ist unbekannt.',
        'assistant',
      ),
    });
  }

  private async reconcileAppend(
    sessionId: string,
    previousMessages: readonly ApiMessage[],
    text: string,
    acknowledge: () => void,
  ): Promise<void> {
    const epoch = this.epoch;
    try {
      const snapshot = await this.transport.readSession(sessionId);
      if (epoch !== this.epoch) return;
      const users = snapshot.messages.filter((message) => message.role === 'user');
      const appended = users[previousMessages.length];
      if (
        prefixMatches(previousMessages, users) &&
        appended?.role === 'user' &&
        appended.text === text
      ) {
        this.setState({
          ...presentSnapshot(snapshot, this.mapArtifact),
          composerDisabled: true,
          status: loading('Antwort wird erstellt …', 'assistant'),
        });
        if (epoch !== this.epoch) return;
        this.confirmedMessages = snapshot.messages;
        acknowledge();
        if (epoch !== this.epoch) return;
        await this.generate(sessionId);
        return;
      }
      this.setState({
        ...presentSnapshot(snapshot, this.mapArtifact),
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
    this.setState({
      ...this.stateValue,
      composerDisabled: false,
      status: failure(
        messageFor(error, 'Die Nachricht konnte nicht gesendet werden. Bitte versuche es erneut.'),
        'assistant',
      ),
    });
  }

  private handleTurnFailure(error: unknown): void {
    const turns = this.turnsWithCurrentStatus(
      isKind(error, 'generation_failed') ? 'failed' : 'unknown',
    );
    if (isUnsupportedApiRequest(error)) {
      this.setUnsupportedApiRequest(error, turns);
    } else if (isTerminal(error)) {
      this.setTerminal(error, turns);
    } else if (isKind(error, 'agent_unavailable')) {
      this.setAgentUnavailable(turns);
    } else if (isKind(error, 'generation_failed')) {
      this.setState({
        ...this.stateValue,
        turns,
        composerDisabled: false,
        status: failure(
          'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
          'assistant',
        ),
      });
    } else {
      this.setState({
        ...this.stateValue,
        turns,
        composerDisabled: true,
        status: failure(
          messageFor(error, 'Die Antwort konnte nicht abgeglichen werden.'),
          'assistant',
        ),
      });
    }
  }

  private setAgentUnavailable(turns: readonly ChatTurn[] = this.stateValue.turns): void {
    this.setState({
      ...this.stateValue,
      turns,
      composerDisabled: true,
      status: failure(
        'Der KI-Agent ist derzeit nicht verfügbar.',
        'conversation',
        'new-session',
        'Erneut versuchen',
      ),
    });
  }

  private setUnsupportedApiRequest(
    error: unknown,
    turns: readonly ChatTurn[] = this.stateValue.turns,
  ): void {
    this.setState({
      ...this.stateValue,
      turns,
      composerDisabled: true,
      status: failure(
        isKind(error, 'method_not_allowed')
          ? 'App und Backend sind nicht kompatibel.'
          : 'Der API-Endpunkt ist nicht verfügbar.',
        'conversation',
      ),
    });
  }

  private setTerminal(error: unknown, turns: readonly ChatTurn[] = this.stateValue.turns): void {
    const exhausted = isKind(error, 'limit_reached');
    this.setState({
      ...this.stateValue,
      turns,
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

  private setState(state: ConversationViewState): void {
    this.stateValue = state;
    this.publish(state);
  }
}

function presentMessage(message: ApiMessage, index: number): ChatTextMessage {
  return {
    kind: 'text',
    id: message.turn_id === null ? `confirmed-${index}-user` : `assistant-${message.turn_id}`,
    role: message.role,
    text: message.text,
  };
}

function presentSnapshot(
  snapshot: SessionSnapshotResponse,
  mapArtifact: ArtifactMapper,
): Pick<ConversationViewState, 'content' | 'turns'> {
  return {
    content: presentTimeline(snapshot.timeline, snapshot.artifacts, mapArtifact).content,
    turns: snapshot.turns.map(presentTurn),
  };
}

function presentTurn(turn: SessionSnapshotResponse['turns'][number]): ChatTurn {
  return {
    id: turn.turn_id,
    userMessageId: turn.user_message_id,
    status:
      turn.status === 'completed'
        ? 'completed'
        : turn.status === 'generation_failed' || turn.status === 'conflict'
          ? 'failed'
          : 'active',
  };
}

function presentTimeline(
  timeline: SessionSnapshotResponse['timeline'],
  artifacts: readonly ArtifactResponse[],
  mapArtifact: ArtifactMapper,
): { readonly content: readonly ChatContent[]; readonly responseTurnIds: ReadonlySet<string> } {
  const envelopes = new Map(artifacts.map((artifact) => [artifact.artifact_id, artifact]));
  const responseTurnIds = new Set<string>();
  const content = timeline.flatMap((item): ChatContent[] => {
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
            id: `tool-${item.execution_id}`,
            name: item.name,
            status: item.status,
            turnId: item.turn_id,
          },
        ];
      case 'artifact': {
        const envelope = envelopes.get(item.artifact_id);
        const artifact = envelope === undefined ? null : mapArtifact(envelope);
        if (artifact !== null) responseTurnIds.add(item.turn_id);
        return artifact === null ? [] : [{ ...artifact, turnId: item.turn_id }];
      }
      case 'failure':
        return [
          {
            kind: 'failure',
            id: `failure-${item.turn_id}`,
            turnId: item.turn_id,
            text: 'Die Antwort konnte nicht erstellt werden.',
          },
        ];
    }
  });
  return { content, responseTurnIds };
}

function itemIdentity(item: SessionSnapshotResponse['timeline'][number]): string {
  switch (item.kind) {
    case 'message':
    case 'intermediate':
      return item.id;
    case 'tool':
      return `tool-${item.execution_id}`;
    case 'artifact':
      return item.artifact_id;
    case 'failure':
      return `failure-${item.turn_id}`;
  }
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
