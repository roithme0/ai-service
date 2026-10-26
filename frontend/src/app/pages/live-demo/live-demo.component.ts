import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import {
  HttpSessionTransport,
  SessionController,
  type SessionViewState,
} from '@roithme0/chat-ui/conversation';
import {
  ChatUiComponent,
  JSON_ARTIFACT_CAPABILITY,
  type ChatSubmission,
} from '@roithme0/chat-ui/ui';
import { chatUsage } from '../../chat-usage';
import { DemoHeader } from '../../components/demo-header/demo-header.component';

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
  selector: 'app-live-demo',
  imports: [ChatUiComponent, DemoHeader],
  templateUrl: './live-demo.component.html',
  styleUrl: './live-demo.component.scss',
})
export class LiveDemo implements OnInit, OnDestroy {
  protected readonly chat = signal<SessionViewState>(INITIAL_STATE);
  protected readonly usage = computed(() => chatUsage(this.chat().snapshot?.usage));
  private readonly controller = new SessionController(
    new HttpSessionTransport('/api/v1', 'live-demo', 'demo:default'),
    (state) => this.chat.set(state),
  );

  ngOnInit(): void {
    void this.controller.start({ artifact_capabilities: [JSON_ARTIFACT_CAPABILITY] });
  }

  ngOnDestroy(): void {
    this.controller.dispose();
  }

  protected handleMessage(submission: ChatSubmission): void {
    if (this.chat().composerDisabled) return;
    void this.controller.submit(submission.text, submission.acknowledge);
  }

  protected handleStatusAction(actionId: string): void {
    void this.controller.performAction(actionId);
  }
}
