import { Component, OnInit, OnDestroy, signal } from '@angular/core';
import {
  ChatUiComponent,
  JSON_ARTIFACT_CAPABILITY,
  type ChatSubmission,
} from '@roithme0/chat-ui/ui';
import { SessionController, type SessionViewState } from '@roithme0/chat-ui/conversation';
import { DemoTransport } from './demo-transport';

const DEMO_ERROR_MESSAGE =
  'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.';
const DEMO_ACTION_ID = 'demo-noop';

const INITIAL_STATE: SessionViewState = {
  snapshot: null,
  admission: 'idle',
  observation: 'connecting',
  turns: [],
  composerDisabled: true,
  composerEditingDisabled: false,
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
export class App implements OnInit, OnDestroy {
  protected readonly chat = signal<SessionViewState>(INITIAL_STATE);
  private compatibilityFailure = false;
  private readonly controller = new SessionController(new DemoTransport(), (state) =>
    this.publishDemoState(state),
  );

  ngOnInit(): void {
    void this.controller.start({
      artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
    });
  }

  ngOnDestroy(): void {
    this.controller.dispose();
  }

  private publishDemoState(state: SessionViewState): void {
    if (this.compatibilityFailure) {
      this.chat.set(this.compatibilityError(state));
      return;
    }
    if (state.status?.kind === 'error' && state.status.message === DEMO_ERROR_MESSAGE) {
      this.chat.set({
        ...state,
        status: {
          ...state.status,
          action: { id: DEMO_ACTION_ID, label: 'Demo-Aktion (ohne Funktion)' },
        },
      });
      return;
    }
    this.chat.set(state);
  }

  protected handleMessage(submission: ChatSubmission): void {
    if (this.chat().composerDisabled) return;
    const completedRuns = new Set(
      this.chat().snapshot?.history.flatMap((item) =>
        item.part_kind === 'turn' && item.lifecycle.status === 'completed'
          ? [item.lifecycle.run_id]
          : [],
      ),
    );
    if (completedRuns.size >= 3) {
      this.compatibilityFailure = true;
      this.chat.set(this.compatibilityError(this.chat()));
      return;
    }
    void this.controller.submit(submission.text, submission.acknowledge);
  }

  private compatibilityError(state: SessionViewState): SessionViewState {
    return {
      ...state,
      composerDisabled: true,
      status: {
        kind: 'error',
        placement: 'conversation',
        message: 'App und Backend sind nicht kompatibel.',
      },
    };
  }

  protected handleStatusAction(actionId: string): void {
    if (actionId === DEMO_ACTION_ID) return;
    void this.controller.performAction(actionId);
  }
}
