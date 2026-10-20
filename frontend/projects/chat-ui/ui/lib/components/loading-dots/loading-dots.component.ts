import { Component, input } from '@angular/core';

@Component({
  selector: 'ai-chat-loading-dots',
  templateUrl: './loading-dots.svg',
  styles: ':host { display: flex; }',
  host: { role: 'img', '[attr.aria-label]': 'label()' },
})
export class LoadingDotsComponent {
  readonly label = input.required<string>();
}
