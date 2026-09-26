import { Component, OnInit, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui';
import { HttpConversationTransport } from './conversation-api';
import { ConversationController, type ConversationViewState } from './conversation-controller';
import { presentJsonArtifact } from './generic-artifact-mapper';

const INITIAL_STATE: ConversationViewState = {
  content: [],
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
  protected readonly chat = signal<ConversationViewState>(INITIAL_STATE);
  private readonly controller = new ConversationController(
    new HttpConversationTransport('demo', {}),
    presentJsonArtifact,
    (state) => this.chat.set(state),
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
