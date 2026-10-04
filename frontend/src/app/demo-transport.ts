import {
  AgentConfiguration, ConversationApiError, HttpConversationTransport,
  type StreamEvent, type SessionCreationResponse, type UserMessageResponse,
} from '@roithme0/chat-ui/conversation';

const COMPLETED_TURNS_BEFORE_COMPATIBILITY_ERROR = 3;

export class DemoTransport extends HttpConversationTransport {
  private completedTurns = 0;

  constructor() {
    super('/api/v1', AgentConfiguration.demo);
  }

  override async createSession(): Promise<SessionCreationResponse> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    const created = await super.createSession();
    this.completedTurns = 0;
    return created;
  }

  override async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    if (this.completedTurns >= COMPLETED_TURNS_BEFORE_COMPATIBILITY_ERROR) {
      throw new ConversationApiError(405, 'method_not_allowed');
    }
    return super.appendMessage(sessionId, text);
  }

  override async *observeTurn(sessionId: string, turnId: string, signal: AbortSignal): AsyncIterable<StreamEvent> {
    for await (const event of super.observeTurn(sessionId, turnId, signal)) {
      if (event.kind === 'terminal' && event.outcome === 'completed') this.completedTurns += 1;
      yield event;
    }
  }
}
