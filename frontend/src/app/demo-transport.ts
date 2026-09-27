import { AgentConfiguration, HttpConversationTransport, type ApiMessage, type SessionCreation } from '@roithme0/chat-ui/conversation';

export class DemoTransport extends HttpConversationTransport {
  constructor() {
    super('/api/v1', AgentConfiguration.Demo);
  }

  override async createSession(): Promise<SessionCreation> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    return super.createSession();
  }

  override async appendMessage(sessionId: string, text: string): Promise<ApiMessage> {
    await new Promise<void>((resolve) => setTimeout(resolve, 1500));
    return super.appendMessage(sessionId, text);
  }
}
