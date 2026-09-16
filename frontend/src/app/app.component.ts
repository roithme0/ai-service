import { Component, signal } from '@angular/core';
import { ChatUiComponent, type ChatTextMessage } from '@roithme0/chat-ui';
import { DemoChatAdapter } from './demo-chat-adapter';

const INITIAL_MESSAGES: readonly ChatTextMessage[] = [
  {
    id: 'initial-assistant',
    role: 'assistant',
    text: [
      'Tell me what you would like to change about your recipe.',
      '',
      'For example, I can help you:',
      '',
      '- adjust the preparation',
      '- explore ingredient alternatives',
      '- compare practical trade-offs',
    ].join('\n'),
  },
  {
    id: 'initial-user',
    role: 'user',
    text: 'Can you keep the **crispy texture** but use less oil?',
  },
  {
    id: 'initial-assistant-follow-up',
    role: 'assistant',
    text: 'Yes. **Hot circulating air** and a light coating can help. Which cooking equipment do you have available?',
  },
];

@Component({
  selector: 'app-root',
  imports: [ChatUiComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class App {
  protected readonly messages = signal<readonly ChatTextMessage[]>(INITIAL_MESSAGES);
  private readonly demoAdapter = new DemoChatAdapter();

  protected handleMessage(text: string): void {
    this.messages.update((messages) => [...messages, ...this.demoAdapter.createTurn(text)]);
  }
}
