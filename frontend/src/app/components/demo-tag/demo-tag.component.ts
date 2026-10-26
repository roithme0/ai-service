import { Component, input } from '@angular/core';

@Component({
  selector: 'app-demo-tag',
  templateUrl: './demo-tag.component.html',
  styleUrl: './demo-tag.component.scss',
})
export class DemoTag {
  readonly label = input.required<string>();
}
