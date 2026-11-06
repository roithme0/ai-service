import { Directive } from '@angular/core';

@Directive({
  selector: '[aiChatPreventPointerFocus]',
  host: {
    '(pointerdown)': '$event.preventDefault()',
    '(mousedown)': '$event.preventDefault()',
  },
})
export class PreventPointerFocusDirective {}
