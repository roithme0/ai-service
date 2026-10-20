import { Component, input } from '@angular/core';
import type { ChatTextMessage } from '../../models/chat-message';

@Component({
  selector: 'ai-chat-user-message',
  templateUrl: './user-message.component.html',
  styleUrl: './user-message.component.scss',
})
export class UserMessageComponent {
  readonly message = input.required<ChatTextMessage>();
}
