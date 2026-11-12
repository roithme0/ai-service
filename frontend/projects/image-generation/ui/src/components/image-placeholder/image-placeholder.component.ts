import { Component, input } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';

export interface PlaceholderAction {
  readonly label: string;
  readonly action: () => void;
  readonly disabled?: boolean;
}

@Component({
  selector: 'ai-image-generation-image-placeholder',
  standalone: true,
  imports: [MatButtonModule],
  templateUrl: './image-placeholder.component.html',
  styleUrl: './image-placeholder.component.scss',
})
export class ImagePlaceholderComponent {
  readonly error = input<string | null>(null);
  readonly action = input<PlaceholderAction | null>(null);
}
