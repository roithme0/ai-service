import { Component, input, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { renderAssistantMarkdown } from '../../assistant-markdown';
import type { ChatTextMessage } from '../../models/chat-message';
import { PreventPointerFocusDirective } from '../../directives/prevent-pointer-focus.directive';

@Component({
  selector: 'ai-chat-assistant-message',
  imports: [MatIconModule, PreventPointerFocusDirective],
  templateUrl: './assistant-message.component.html',
  styleUrl: './assistant-message.component.scss',
})
export class AssistantMessageComponent {
  readonly message = input.required<ChatTextMessage>();
  readonly showDetailsToggle = input(false);
  readonly detailsExpanded = input(false);
  readonly detailsToggled = output<void>();
  protected readonly renderAssistantMarkdown = renderAssistantMarkdown;
}
