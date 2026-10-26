import { Component, input } from '@angular/core';

@Component({
  selector: 'app-navigation-link',
  templateUrl: './navigation-link.component.html',
  styleUrl: './navigation-link.component.scss',
})
export class NavigationLink {
  readonly direction = input<'back' | 'forward'>('forward');
}
