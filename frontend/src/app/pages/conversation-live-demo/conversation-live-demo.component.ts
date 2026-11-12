import { chatModel } from '../../conversation/chat-model';
import {
  ChangeDetectorRef,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
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
import { MatSnackBar } from '@angular/material/snack-bar';
import { BrowserAudioRecorder } from '@roithme0/chat-ui/recording';
import { HttpTranscriber } from '@roithme0/chat-ui/transcription';
import type { DictationConfig, DictationError } from '@roithme0/chat-ui/ui';
import { chatUsage } from '../../conversation/chat-usage';
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
  selector: 'app-conversation-live-demo',
  imports: [ChatUiComponent, DemoHeader],
  templateUrl: './conversation-live-demo.component.html',
  styleUrl: './conversation-live-demo.component.scss',
})
export class ConversationLiveDemo implements OnInit, OnDestroy {
  private readonly snackBar = inject(MatSnackBar);
  private readonly changeDetector = inject(ChangeDetectorRef);

  private readonly transcriber = new HttpTranscriber('/api/v1');
  protected readonly dictationContextKey = signal('0');
  protected readonly dictation: DictationConfig = {
    createRecorder: (publish) => new BrowserAudioRecorder(publish),
    transcribe: (recording, signal) => this.transcriber.transcribe(recording, signal),
    onError: (error) => this.showDictationError(error),
  };
  protected readonly chat = signal<SessionViewState>(INITIAL_STATE);
  protected readonly model = computed(() => chatModel(this.chat().snapshot?.model));
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
    if (actionId === 'new-session') {
      this.dictationContextKey.update((key) => String(Number(key) + 1));
      this.changeDetector.detectChanges();
    }
    void this.controller.performAction(actionId);
  }

  private showDictationError(error: DictationError): void {
    let message: string;
    if (error.kind !== 'recording') {
      message = 'Die Aufnahme konnte nicht transkribiert werden.';
    } else if (error.reason === 'permission-denied') {
      message = 'Der Zugriff auf das Mikrofon wurde verweigert.';
    } else {
      message = 'Die Aufnahme konnte nicht abgeschlossen werden.';
    }

    this.snackBar.open(message, 'OK', { duration: 6000, politeness: 'assertive' });
  }
}
