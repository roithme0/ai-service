import type { PresentedSession } from '@roithme0/chat-ui/conversation';
import type { ChatModel } from '@roithme0/chat-ui/ui';

export function chatModel(model: PresentedSession['model'] | undefined): ChatModel | null {
  return model ? { name: model.name, reasoningEffort: model.reasoning_effort } : null;
}
