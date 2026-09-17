import type { ChatConversationStatus, ChatTextMessage } from '@roithme0/chat-ui';
import {
  RecipeChatApiError,
  RecipeChatNetworkError,
  type ApiMessage,
  type RecipeChatTransport,
  type SessionSnapshot,
} from './recipe-chat-api';

export interface RecipeChatViewState {
  readonly messages: readonly ChatTextMessage[];
  readonly composerDisabled: boolean;
  readonly status: ChatConversationStatus | null;
}

const INITIAL_STATE: RecipeChatViewState = {
  messages: [],
  composerDisabled: true,
  status: loading('Unterhaltung wird gestartet …', 'conversation'),
};

export class RecipeChatController {
  private sessionId: string | null = null;
  private stateValue = INITIAL_STATE;

  constructor(
    private readonly transport: RecipeChatTransport,
    private readonly publish: (state: RecipeChatViewState) => void,
  ) {}

  get state(): RecipeChatViewState {
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
      this.setState({ messages: [], composerDisabled: false, status: null });
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
    const previousMessages = this.stateValue.messages;
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
      if (error instanceof RecipeChatNetworkError) {
        await this.reconcileAppend(sessionId, previousMessages, text, acknowledge);
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
      messages: [
        ...this.stateValue.messages,
        presentMessage(message, this.stateValue.messages.length),
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
        messages: [
          ...this.stateValue.messages,
          presentMessage(result.message, this.stateValue.messages.length),
        ],
        composerDisabled: false,
        status: null,
      });
    } catch (error: unknown) {
      if (error instanceof RecipeChatNetworkError || isKind(error, 'busy')) {
        await this.reconcileTurn(sessionId);
        return;
      }
      this.handleTurnFailure(error);
    }
  }

  private async reconcileAppend(
    sessionId: string,
    previousMessages: readonly ChatTextMessage[],
    text: string,
    acknowledge: () => void,
  ): Promise<void> {
    try {
      const snapshot = await this.transport.readSession(sessionId);
      const messages = presentMessages(snapshot.messages);
      const appended = snapshot.messages[previousMessages.length];
      if (
        prefixMatches(previousMessages, snapshot.messages) &&
        appended?.role === 'user' &&
        appended.text === text
      ) {
        this.setState({
          messages,
          composerDisabled: true,
          status: loading('Antwort wird erstellt …', 'assistant'),
        });
        acknowledge();
        await this.generate(sessionId);
        return;
      }
      this.setState({
        messages,
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
        error instanceof RecipeChatNetworkError
          ? error
          : new RecipeChatNetworkError('Abgleich fehlgeschlagen.', { cause: error }),
      );
    }
  }

  private applyTurnSnapshot(snapshot: SessionSnapshot): void {
    const messages = presentMessages(snapshot.messages);
    const last = snapshot.messages.at(-1);
    if (last?.role === 'assistant') {
      this.setState({ messages, composerDisabled: false, status: null });
      return;
    }
    if (snapshot.terminal_turn_kind === 'generation_failed') {
      this.setState({
        messages,
        composerDisabled: false,
        status: failure(
          'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
          'assistant',
        ),
      });
      return;
    }
    this.setState({
      messages,
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
    if (isTerminal(error)) {
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
    } else if (isKind(error, 'generator_unavailable')) {
      this.setState({
        ...this.stateValue,
        composerDisabled: true,
        status: failure(
          'Das KI-Modell ist derzeit nicht verfügbar.',
          'assistant',
          'retry-turn',
          'Erneut versuchen',
        ),
      });
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

  private setState(state: RecipeChatViewState): void {
    this.stateValue = state;
    this.publish(state);
  }
}

function presentMessages(messages: readonly ApiMessage[]): readonly ChatTextMessage[] {
  return messages.map(presentMessage);
}

function presentMessage(message: ApiMessage, index: number): ChatTextMessage {
  return { id: `confirmed-${index}-${message.role}`, role: message.role, text: message.text };
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
  return error instanceof RecipeChatApiError && error.kind === kind;
}

function isTerminal(error: unknown): boolean {
  return isKind(error, 'expired') || isKind(error, 'unknown') || isKind(error, 'limit_reached');
}

function messageFor(error: unknown, fallback: string): string {
  return error instanceof RecipeChatNetworkError ? error.message : fallback;
}
