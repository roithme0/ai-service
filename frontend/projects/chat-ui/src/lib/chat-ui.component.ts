import { NgTemplateOutlet } from '@angular/common';
import { Component, TemplateRef, input } from '@angular/core';
import type { ChatDemoRendererContext, IntegrationDemoArtifact } from './chat-demo-artifact';

@Component({
  selector: 'ai-chat-ui',
  imports: [NgTemplateOutlet],
  templateUrl: './chat-ui.component.html',
  styleUrl: './chat-ui.component.scss',
})
export class ChatUiComponent {
  readonly bannerTitle = input.required<string>();
  readonly bannerDescription = input.required<string>();
  readonly artifact = input<IntegrationDemoArtifact>();
  readonly renderer = input<TemplateRef<ChatDemoRendererContext>>();
}
