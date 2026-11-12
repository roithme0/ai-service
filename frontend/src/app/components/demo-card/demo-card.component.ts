import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DemoTag } from '../demo-tag/demo-tag.component';
import { NavigationLink } from '../navigation-link/navigation-link.component';

@Component({
  selector: 'app-demo-card',
  imports: [RouterLink, DemoTag, NavigationLink],
  templateUrl: './demo-card.component.html',
  styleUrl: './demo-card.component.scss',
})
export class DemoCard {
  readonly route = input.required<string>();
  readonly title = input.required<string>();
  readonly tag = input.required<string>();
}
