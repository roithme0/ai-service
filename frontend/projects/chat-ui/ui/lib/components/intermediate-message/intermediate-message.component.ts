import { Component, input } from '@angular/core';
import { renderAssistantMarkdown } from '../../assistant-markdown';
import type { ChatIntermediateMessage } from '../../models/chat-message';

@Component({
  selector: 'ai-chat-intermediate-message',
  templateUrl: './intermediate-message.component.html',
  styleUrl: './intermediate-message.component.scss',
  host: {
    role: 'article',
    class: 'message message--intermediate',
    'aria-label': 'Zwischenmeldung des Assistenten',
  },
})
export class IntermediateMessageComponent {
  readonly message = input.required<ChatIntermediateMessage>();
  protected readonly renderAssistantMarkdown = renderAssistantMarkdown;
}
