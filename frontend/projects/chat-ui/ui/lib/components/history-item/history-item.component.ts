import { Component, input } from '@angular/core';

@Component({
  selector: 'ai-chat-history-item',
  templateUrl: './history-item.component.html',
  styleUrl: './history-item.component.scss',
})
export class HistoryItemComponent {
  readonly collapsed = input(false);
}
