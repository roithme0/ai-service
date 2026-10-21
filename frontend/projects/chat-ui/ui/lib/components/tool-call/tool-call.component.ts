import { Component, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import type { ChatToolCall, ChatToolStatus } from '../../models/chat-message';

@Component({
  selector: 'ai-chat-tool-call',
  imports: [MatIconModule],
  templateUrl: './tool-call.component.html',
  styleUrl: './tool-call.component.scss',
  host: {
    role: 'article',
    'aria-label': 'Werkzeugaufruf',
  },
})
export class ToolCallComponent {
  readonly toolCall = input.required<ChatToolCall>();
  protected readonly toolStatusLabels: Record<ChatToolStatus, string> = {
    completed: 'Abgeschlossen',
    failed: 'Fehlgeschlagen',
    not_executed: 'Nicht ausgeführt',
    outcome_unknown: 'Ergebnis unklar',
    requested: 'Angefragt',
    running: 'Wird ausgeführt',
  };
}
