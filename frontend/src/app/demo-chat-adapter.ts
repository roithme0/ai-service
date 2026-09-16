import type { ChatTextMessage } from '@roithme0/chat-ui';

const FIXED_RESPONSE = [
  'This is a **fixed local response** from the demo adapter.',
  '',
  '- No message was sent to a backend.',
  '- The shared chat UI only emitted your submitted text.',
].join('\n');

export class DemoChatAdapter {
  private nextMessageNumber = 1;

  createTurn(text: string): readonly ChatTextMessage[] {
    const turnNumber = this.nextMessageNumber++;
    return [
      {
        id: `demo-user-${turnNumber}`,
        role: 'user',
        text,
      },
      {
        id: `demo-assistant-${turnNumber}`,
        role: 'assistant',
        text: FIXED_RESPONSE,
      },
    ];
  }
}
