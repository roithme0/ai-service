export type ChatMessageRole = 'user' | 'assistant';

export interface ChatTextMessage {
  readonly id: string;
  readonly role: ChatMessageRole;
  readonly text: string;
}
