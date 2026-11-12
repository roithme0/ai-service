import { MatButtonModule } from '@angular/material/button';
import { Component, computed, ElementRef, inject, input, output, viewChild } from '@angular/core';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconModule, MatIconRegistry } from '@angular/material/icon';
import type { CompletedSnapshot, Snapshot } from '@roithme0/image-generation/controller';
import { registerUiIcons } from '../../../../../shared/icons';
import { ImagePlaceholderComponent } from '../image-placeholder/image-placeholder.component';

interface ImagePreview {
  readonly url: string;
  readonly snapshot: CompletedSnapshot;
}

@Component({
  selector: 'ai-image-generation-outcome-panel',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, ImagePlaceholderComponent],
  templateUrl: './outcome-panel.component.html',
  styleUrls: ['../panel.scss', './outcome-panel.component.scss'],
})
export class ImageGenerationOutcomePanelComponent {
  readonly contentError = input<string | null>(null);
  readonly editable = input(true);
  readonly error = input<string | null>(null);
  readonly failure = input<string | null>(null);
  readonly image = input<ImagePreview | null>(null);
  readonly loading = input(false);
  readonly pending = input(false);
  readonly primaryLabel = input<string | null>(null);
  readonly snapshot = input<Snapshot | null>(null);

  readonly download = output<void>();
  readonly handoff = output<void>();
  readonly imageError = output<void>();
  readonly refine = output<void>();
  readonly retry = output<void>();
  readonly retryImage = output<void>();

  readonly imageRetryAction = {
    label: 'Erneut versuchen',
    action: (): void => this.retryImage.emit(),
  };
  readonly failureRetryAction = computed(() => ({
    label: 'Erneut versuchen',
    action: (): void => this.retry.emit(),
    disabled: this.pending(),
  }));

  readonly metadata = computed(() => {
    const snapshot = this.image()?.snapshot ?? this.snapshot();
    return snapshot?.status !== 'running' ? snapshot : null;
  });

  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  constructor() {
    registerUiIcons(inject(MatIconRegistry), inject(DomSanitizer));
  }

  focusHeading(): void {
    this.heading()?.nativeElement.focus();
  }

  cost(value: string | null): string {
    return value === null ? 'Nicht verfügbar' : `$${value}`;
  }
}
