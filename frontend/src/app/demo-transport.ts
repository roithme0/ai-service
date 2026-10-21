import {
  HttpSessionTransport,
  type SessionCreated,
  type SessionCreationRequest,
  type TurnAccepted,
} from '@roithme0/chat-ui/conversation';

export class DemoTransport extends HttpSessionTransport {
  constructor() {
    super('/api/v1', 'demo', 'demo:default');
  }

  override async createSession(initialization?: SessionCreationRequest): Promise<SessionCreated> {
    await new Promise<void>((resolve) => setTimeout(resolve, 500));
    return super.createSession(initialization);
  }

  override async submitPrompt(sessionId: string, prompt: string): Promise<TurnAccepted> {
    await new Promise<void>((resolve) => setTimeout(resolve, 500));
    return super.submitPrompt(sessionId, prompt);
  }
}
