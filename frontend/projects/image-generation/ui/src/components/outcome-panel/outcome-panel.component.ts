import { MatButtonModule } from '@angular/material/button';
import { Component, computed, ElementRef, input, output, viewChild } from '@angular/core';
import type { CompletedSnapshot, Snapshot } from '@roithme0/image-generation/controller';

interface ImagePreview {
  readonly url: string;
  readonly snapshot: CompletedSnapshot;
}

@Component({
  selector: 'ai-image-generation-outcome-panel',
  standalone: true,
  imports: [MatButtonModule],
  templateUrl: './outcome-panel.component.html',
  styleUrls: ['../panel.scss', './outcome-panel.component.scss'],
})
export class ImageGenerationOutcomePanelComponent {
  readonly image = input<ImagePreview | null>(null);
  readonly snapshot = input<Snapshot | null>(null);
  readonly instructions = input.required<string>();
  readonly failure = input<string | null>(null);
  readonly error = input<string | null>(null);
  readonly contentError = input<string | null>(null);
  readonly loading = input(false);
  readonly pending = input(false);
  readonly primaryLabel = input<string | null>(null);
  readonly refine = output<void>();
  readonly download = output<void>();
  readonly handoff = output<void>();
  readonly retryImage = output<void>();
  readonly imageError = output<void>();
  readonly metadata = computed(() => {
    const snapshot = this.image()?.snapshot ?? this.snapshot();
    return snapshot?.status !== 'running' ? snapshot : null;
  });
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  focusHeading(): void {
    this.heading()?.nativeElement.focus();
  }

  cost(value: string | null): string {
    return value === null ? 'Unavailable' : `$${value}`;
  }
}
