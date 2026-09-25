import type { ChatArtifact, ChatContent, ChatConversationStatus, ChatTextMessage } from '@roithme0/chat-ui';
import {
  ConversationApiError,
  ConversationNetworkError,
  type ApiArtifact,
  type ApiMessage,
  type ConversationTransport,
  type SessionSnapshot,
} from './conversation-api';

export type ArtifactMapper = (artifact: ApiArtifact) => ChatArtifact | null;

export interface ConversationViewState {
  readonly content: readonly ChatContent[];
  readonly composerDisabled: boolean;
  readonly status: ChatConversationStatus | null;
}

const INITIAL_STATE: ConversationViewState = {
  content: [],
  composerDisabled: true,
  status: loading('Unterhaltung wird gestartet …', 'conversation'),
};

export class ConversationController {
  private sessionId: string | null = null;
  private stateValue = INITIAL_STATE;

  constructor(
    private readonly transport: ConversationTransport,
    private readonly mapArtifact: ArtifactMapper,
    private readonly publish: (state: ConversationViewState) => void,
  ) {}

  get state(): ConversationViewState {
    return this.stateValue;
  }

  async start(): Promise<void> {
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: loading('Unterhaltung wird gestartet …', 'conversation'),
    });
    try {
      const created = await this.transport.createSession();
      this.sessionId = created.session_id;
      this.setState({ content: [], composerDisabled: false, status: null });
    } catch (error: unknown) {
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
    const previousContent = this.stateValue.content;
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: loading('Nachricht wird gesendet …', 'assistant'),
    });
    try {
      const accepted = await this.transport.appendMessage(sessionId, text);
      this.acceptMessage(accepted, acknowledge);
      await this.generate(sessionId);
    } catch (error: unknown) {
      if (error instanceof ConversationNetworkError) {
        await this.reconcileAppend(sessionId, previousContent, text, acknowledge);
        return;
      }
      this.handleAppendFailure(error);
    }
  }

  async performAction(actionId: string): Promise<void> {
    if (actionId === 'new-session') {
      await this.start();
    } else if (actionId === 'retry-turn' && this.sessionId !== null) {
      await this.generate(this.sessionId);
    }
  }

  private acceptMessage(message: ApiMessage, acknowledge: () => void): void {
    this.setState({
      content: [
        ...this.stateValue.content,
        presentMessage(message, textContent(this.stateValue.content).length),
      ],
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    acknowledge();
  }

  private async generate(sessionId: string): Promise<void> {
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: loading('Antwort wird erstellt …', 'assistant'),
    });
    try {
      const result = await this.transport.generateTurn(sessionId);
      this.setState({
        content: [
          ...this.stateValue.content,
          ...presentArtifacts(result.artifacts, this.mapArtifact),
          presentMessage(result.message, textContent(this.stateValue.content).length),
        ],
        composerDisabled: false,
        status: null,
      });
    } catch (error: unknown) {
      if (error instanceof ConversationNetworkError || isKind(error, 'busy')) {
        await this.reconcileTurn(sessionId);
        return;
      }
      this.handleTurnFailure(error);
    }
  }

  private async reconcileAppend(
    sessionId: string,
    previousContent: readonly ChatContent[],
    text: string,
    acknowledge: () => void,
  ): Promise<void> {
    try {
      const snapshot = await this.transport.readSession(sessionId);
      const previousMessages = previousContent.filter(isTextMessage);
      const appended = snapshot.messages[previousMessages.length];
      if (
        prefixMatches(previousMessages, snapshot.messages) &&
        appended?.role === 'user' &&
        appended.text === text
      ) {
        this.setState({
          content: presentSnapshot(snapshot, this.mapArtifact),
          composerDisabled: true,
          status: loading('Antwort wird erstellt …', 'assistant'),
        });
        acknowledge();
        await this.generate(sessionId);
        return;
      }
      this.setState({
        content: presentSnapshot(snapshot, this.mapArtifact),
        composerDisabled: false,
        status: failure(
          'Die Nachricht konnte nicht gesendet werden. Bitte versuche es erneut.',
          'assistant',
        ),
      });
    } catch (error: unknown) {
      this.handleAppendFailure(error);
    }
  }

  private async reconcileTurn(sessionId: string): Promise<void> {
    try {
      const snapshot = await this.transport.readSession(sessionId);
      this.applyTurnSnapshot(snapshot);
    } catch (error: unknown) {
      this.handleTurnFailure(
        error instanceof ConversationNetworkError || isKind(error, 'agent_unavailable')
          ? error
          : new ConversationNetworkError('Abgleich fehlgeschlagen.', { cause: error }),
      );
    }
  }

  private applyTurnSnapshot(snapshot: SessionSnapshot): void {
    const content = presentSnapshot(snapshot, this.mapArtifact);
    const last = snapshot.messages.at(-1);
    if (last?.role === 'assistant') {
      this.setState({ content, composerDisabled: false, status: null });
      return;
    }
    if (snapshot.terminal_turn_kind === 'generation_failed') {
      this.setState({
        content,
        composerDisabled: false,
        status: failure(
          'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
          'assistant',
        ),
      });
      return;
    }
    this.setState({
      content,
      composerDisabled: true,
      status: failure(
        'Der Status der Antwort ist noch unklar.',
        'assistant',
        'retry-turn',
        'Erneut versuchen',
      ),
    });
  }

  private handleAppendFailure(error: unknown): void {
    if (isKind(error, 'agent_unavailable')) {
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
    if (isTerminal(error)) {
      this.setTerminal(error);
    } else if (isKind(error, 'agent_unavailable')) {
      this.setAgentUnavailable();
    } else if (isKind(error, 'generation_failed')) {
      this.setState({
        ...this.stateValue,
        composerDisabled: false,
        status: failure(
          'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
          'assistant',
        ),
      });
    } else {
      this.setState({
        ...this.stateValue,
        composerDisabled: true,
        status: failure(
          messageFor(error, 'Die Antwort konnte nicht abgeglichen werden.'),
          'assistant',
          'retry-turn',
          'Erneut versuchen',
        ),
      });
    }
  }

  private setAgentUnavailable(): void {
    this.setState({
      ...this.stateValue,
      composerDisabled: true,
      status: failure('Der KI-Agent ist derzeit nicht verfügbar.', 'conversation', 'new-session', 'Erneut versuchen'),
    });
  }

  private setTerminal(error: unknown): void {
    const exhausted = isKind(error, 'limit_reached');
    this.setState({
      ...this.stateValue,
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

function presentMessages(messages: readonly ApiMessage[]): readonly ChatTextMessage[] {
  return messages.map(presentMessage);
}

function presentMessage(message: ApiMessage, index: number): ChatTextMessage {
  return {
    kind: 'text',
    id: message.turn_id === null ? `confirmed-${index}-user` : `assistant-${message.turn_id}`,
    role: message.role,
    text: message.text,
  };
}

function presentSnapshot(snapshot: SessionSnapshot, mapArtifact: ArtifactMapper): readonly ChatContent[] {
  if (snapshot.artifacts.length === 0) return presentMessages(snapshot.messages);
  return snapshot.messages.flatMap((message, index) => [
    ...presentArtifacts(snapshot.artifacts.filter((artifact) => artifact.turn_id === message.turn_id), mapArtifact),
    presentMessage(message, index),
  ]);
}

function presentArtifacts(artifacts: readonly ApiArtifact[], mapArtifact: ArtifactMapper): readonly ChatArtifact[] {
  return [...artifacts]
    .sort((left, right) => left.order - right.order)
    .map(mapArtifact)
    .filter((artifact): artifact is ChatArtifact => artifact !== null);
}

function isTextMessage(content: ChatContent): content is ChatTextMessage {
  return content.kind === 'text';
}

function textContent(content: readonly ChatContent[]): readonly ChatTextMessage[] {
  return content.filter(isTextMessage);
}

function prefixMatches(
  previous: readonly ChatTextMessage[],
  current: readonly ApiMessage[],
): boolean {
  return previous.every(
    (message, index) =>
      current[index]?.role === message.role && current[index]?.text === message.text,
  );
}

function loading(message: string, placement: 'conversation' | 'assistant'): ChatConversationStatus {
  return { kind: 'loading', message, placement };
}

function failure(
  message: string,
  placement: 'conversation' | 'assistant',
  id?: string,
  label?: string,
): ChatConversationStatus {
  return id === undefined || label === undefined
    ? { kind: 'error', message, placement }
    : { kind: 'error', message, placement, action: { id, label } };
}

function isKind(error: unknown, kind: string): boolean {
  return error instanceof ConversationApiError && error.kind === kind;
}

function isTerminal(error: unknown): boolean {
  return isKind(error, 'expired') || isKind(error, 'unknown') || isKind(error, 'limit_reached');
}

function messageFor(error: unknown, fallback: string): string {
  if (isKind(error, 'agent_unavailable')) return 'Der KI-Agent ist derzeit nicht verfügbar.';
  return error instanceof ConversationNetworkError ? error.message : fallback;
}
