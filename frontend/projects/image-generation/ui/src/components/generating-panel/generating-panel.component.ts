import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Component, ElementRef, input, output, viewChild } from '@angular/core';
import type { Admission, Observation } from '@roithme0/image-generation/controller';

@Component({
  selector: 'ai-image-generation-generating-panel',
  standalone: true,
  imports: [MatButtonModule, MatProgressSpinnerModule],
  templateUrl: './generating-panel.component.html',
  styleUrls: ['../panel.scss', './generating-panel.component.scss'],
})
export class ImageGenerationGeneratingPanelComponent {
  readonly admission = input.required<Admission>();
  readonly observation = input.required<Observation>();
  readonly editable = input(true);
  readonly retry = output<void>();
  readonly edit = output<void>();
  readonly pending = input(false);
  readonly error = input<string | null>(null);
  readonly recover = output<void>();
  readonly reconnect = output<void>();
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  focusHeading(): void {
    this.heading()?.nativeElement.focus();
  }
}
