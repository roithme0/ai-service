import { Component, OnInit, OnDestroy, computed, signal } from '@angular/core';
import {
  ChatUiComponent,
  JSON_ARTIFACT_CAPABILITY,
  type ChatSubmission,
  type ChatUsage,
} from '@roithme0/chat-ui/ui';
import { SessionController, type SessionViewState } from '@roithme0/chat-ui/conversation';
import { VisualDemoTransport } from './visual-demo-transport';

const VISUAL_DEMO_ERROR_MESSAGE =
  'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.';
const VISUAL_DEMO_ACTION_ID = 'visual-demo-noop';

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
  protected readonly usage = computed<ChatUsage | null>(() => {
    const usage = this.chat().snapshot?.usage;
    return usage
      ? {
          totalTokens: usage.total_tokens,
          estimatedCostUsd: usage.estimated_cost_usd,
          inputTokens: usage.input_tokens,
          outputTokens: usage.output_tokens,
          reasoningTokens: usage.reasoning_tokens,
          cacheReadTokens: usage.cache_read_tokens,
          cacheWriteTokens: usage.cache_write_tokens,
          requests: usage.requests,
          toolCalls: usage.tool_calls,
        }
      : null;
  });
  private compatibilityFailure = false;
  private readonly controller = new SessionController(new VisualDemoTransport(), (state) =>
    this.publishVisualDemoState(state),
  );

  ngOnInit(): void {
    void this.controller.start({
      artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
    });
  }

  ngOnDestroy(): void {
    this.controller.dispose();
  }

  private publishVisualDemoState(state: SessionViewState): void {
    if (this.compatibilityFailure) {
      this.chat.set(this.compatibilityError(state));
      return;
    }
    if (state.status?.kind === 'error' && state.status.message === VISUAL_DEMO_ERROR_MESSAGE) {
      this.chat.set({
        ...state,
        status: {
          ...state.status,
          action: { id: VISUAL_DEMO_ACTION_ID, label: 'Demo-Aktion (ohne Funktion)' },
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
    if (actionId === VISUAL_DEMO_ACTION_ID) return;
    void this.controller.performAction(actionId);
  }
}
