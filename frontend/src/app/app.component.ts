import { Component, OnInit, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui';
import { HttpRecipeChatTransport } from './recipe-chat-api';
import { RecipeChatController, type RecipeChatViewState } from './recipe-chat-controller';

const INITIAL_STATE: RecipeChatViewState = {
  messages: [],
  composerDisabled: true,
  status: {
    kind: 'loading',
    message: 'Unterhaltung wird gestartet …',
    placement: 'conversation',
  },
};

@Component({
  selector: 'app-root',
  imports: [ChatUiComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class App implements OnInit {
  protected readonly chat = signal<RecipeChatViewState>(INITIAL_STATE);
  private readonly controller = new RecipeChatController(new HttpRecipeChatTransport(), (state) =>
    this.chat.set(state),
  );

  ngOnInit(): void {
    void this.controller.start();
  }

  protected handleMessage(submission: ChatSubmission): void {
    void this.controller.submit(submission.text, submission.acknowledge);
  }

  protected handleStatusAction(actionId: string): void {
    void this.controller.performAction(actionId);
  }
}
