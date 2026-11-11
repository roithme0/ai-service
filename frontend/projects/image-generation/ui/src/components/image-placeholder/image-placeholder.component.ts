import { Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'ai-image-generation-image-placeholder',
  standalone: true,
  imports: [MatButtonModule],
  templateUrl: './image-placeholder.component.html',
  styleUrl: './image-placeholder.component.scss',
})
export class ImagePlaceholderComponent {
  readonly error = input<string | null>(null);
  readonly retry = output<void>();
}
