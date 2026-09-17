export type ChatMessageRole = 'user' | 'assistant';

export interface ChatTextMessage {
  readonly id: string;
  readonly role: ChatMessageRole;
  readonly text: string;
}

export interface ChatSubmission {
  readonly text: string;
  readonly acknowledge: () => void;
}

export interface ChatStatusAction {
  readonly id: string;
  readonly label: string;
}

export interface ChatConversationStatus {
  readonly kind: 'loading' | 'error';
  readonly message: string;
  readonly placement: 'conversation' | 'assistant';
  readonly action?: ChatStatusAction;
}
