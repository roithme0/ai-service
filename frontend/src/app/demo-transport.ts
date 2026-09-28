import { AgentConfiguration, HttpConversationTransport, type UserMessageResponse, type SessionCreationResponse } from '@roithme0/chat-ui/conversation';

export class DemoTransport extends HttpConversationTransport {
  constructor() {
    super('/api/v1', AgentConfiguration.demo);
  }

  override async createSession(): Promise<SessionCreationResponse> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    return super.createSession();
  }

  override async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    return super.appendMessage(sessionId, text);
  }
}
