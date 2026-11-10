import { Component, input, output } from '@angular/core';

export interface SectionNavItem {
  id: string;
  label: string;
}

@Component({
  selector: 'app-section-nav',
  templateUrl: './section-nav.component.html',
  styleUrl: './section-nav.component.scss',
})
export class SectionNavComponent {
  readonly items = input.required<readonly SectionNavItem[]>();
  readonly activeId = input.required<string>();
  readonly label = input.required<string>();
  readonly selected = output<string>();
}
