import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DemoTag } from '../demo-tag/demo-tag.component';
import { NavigationLink } from '../navigation-link/navigation-link.component';

@Component({
  selector: 'app-demo-header',
  imports: [RouterLink, DemoTag, NavigationLink],
  templateUrl: './demo-header.component.html',
  styleUrl: './demo-header.component.scss',
})
export class DemoHeader {
  readonly label = input.required<string>();
  readonly tag = input.required<string>();
}
