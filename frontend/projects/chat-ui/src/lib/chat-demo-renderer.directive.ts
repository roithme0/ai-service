import { Directive, TemplateRef, inject } from '@angular/core';
import type { ChatDemoRendererContext } from './chat-demo-artifact';

@Directive({
  selector: 'ng-template[aiChatDemoRenderer]',
  exportAs: 'aiChatDemoRenderer',
})
export class ChatDemoRendererDirective {
  readonly template = inject<TemplateRef<ChatDemoRendererContext>>(TemplateRef);

  static ngTemplateContextGuard(
    _directive: ChatDemoRendererDirective,
    _context: unknown,
  ): _context is ChatDemoRendererContext {
    return true;
  }
}
