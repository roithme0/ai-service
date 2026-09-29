import {
  AgentConfiguration, ConversationApiError, HttpConversationTransport,
  type CompletedTurnResponse, type SessionCreationResponse, type UserMessageResponse,
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

  override async generateTurn(sessionId: string): Promise<CompletedTurnResponse> {
    const turn = await super.generateTurn(sessionId);
    this.completedTurns += 1;
    return turn;
  }
}
