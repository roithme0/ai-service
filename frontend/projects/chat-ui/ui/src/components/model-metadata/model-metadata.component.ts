import { Component, input } from '@angular/core';
import type { ChatModel } from '../../models/chat-model';

@Component({
  selector: 'ai-chat-model-metadata',
  templateUrl: './model-metadata.component.html',
  styleUrl: './model-metadata.component.scss',
})
export class ModelMetadataComponent {
  readonly model = input.required<ChatModel>();
}
