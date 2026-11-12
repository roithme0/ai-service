import { AfterViewChecked, Component, ElementRef, input, output, viewChild } from '@angular/core';

export interface SectionNavItem {
  id: string;
  label: string;
}

@Component({
  selector: 'app-section-nav',
  templateUrl: './section-nav.component.html',
  styleUrl: './section-nav.component.scss',
})
export class SectionNavComponent implements AfterViewChecked {
  readonly items = input.required<readonly SectionNavItem[]>();
  readonly activeId = input.required<string>();
  readonly label = input.required<string>();
  readonly selected = output<string>();
  private readonly track = viewChild.required<ElementRef<HTMLElement>>('track');
  private lastActive = '';

  ngAfterViewChecked(): void {
    const active = this.activeId();
    if (active === this.lastActive) return;
    this.lastActive = active;
    const button = this.track().nativeElement.querySelector<HTMLButtonElement>('[aria-current]');
    button?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }
}
