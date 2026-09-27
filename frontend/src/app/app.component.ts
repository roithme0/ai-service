import { Component, OnInit, signal } from '@angular/core';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import { ConversationController, type ConversationViewState } from '@roithme0/chat-ui/conversation';
import { DemoTransport } from './demo-transport';

const DEMO_ERROR_MESSAGE = 'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.';
const DEMO_ACTION_ID = 'demo-noop';

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
    new DemoTransport(),
    (state) => this.chat.set(
      state.status?.kind === 'error' && state.status.message === DEMO_ERROR_MESSAGE
        ? {
            ...state,
            status: {
              ...state.status,
              action: { id: DEMO_ACTION_ID, label: 'Demo-Aktion (ohne Funktion)' },
            },
          }
        : state,
    ),
  );

  ngOnInit(): void {
    void this.controller.start();
  }

  protected handleMessage(submission: ChatSubmission): void {
    void this.controller.submit(submission.text, submission.acknowledge);
  }

  protected handleStatusAction(actionId: string): void {
    if (actionId === DEMO_ACTION_ID) return;
    void this.controller.performAction(actionId);
  }
}
