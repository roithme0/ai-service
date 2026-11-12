import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Component, computed, ElementRef, input, output, viewChild } from '@angular/core';
import type { Admission, Observation } from '@roithme0/image-generation/controller';
import type { OutputEmitterRef } from '@angular/core';

interface Interruption {
  heading: string;
  message: string;
  label: string | null;
  action: OutputEmitterRef<void> | null;
  alert: boolean;
  editable: boolean;
}

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
  readonly submissionUnknown = input(false);
  readonly loading = computed(() => ({
    heading: 'Bild wird erstellt',
    message:
      this.admission() === 'idle' && !this.pending()
        ? 'Bilderstellung wird vorbereitet'
        : this.admission() === 'accepted'
          ? 'Bild wird erstellt'
          : 'Anfrage wird gesendet',
  }));
  readonly interruption = computed<Interruption | null>(() => {
    if (this.submissionUnknown()) {
      return {
        heading: 'Anfragestatus unbekannt',
        message: 'Der Status der Anfrage konnte nicht bestätigt werden.',
        label: null,
        action: null,
        alert: true,
        editable: false,
      };
    }
    if (this.admission() === 'rejected') {
      return {
        heading: 'Anfrage fehlgeschlagen',
        message: this.error() ?? 'Die Anfrage wurde abgelehnt.',
        label: 'Erneut versuchen',
        action: this.retry,
        alert: true,
        editable: true,
      };
    }
    if (this.admission() === 'uncertain') {
      return {
        heading: 'Anfrage nicht bestätigt',
        message: 'Das Absenden konnte nicht bestätigt werden',
        label: 'Wiederherstellen',
        action: this.recover,
        alert: false,
        editable: false,
      };
    }
    if (this.observation() === 'lost') {
      return {
        heading: 'Verbindung unterbrochen',
        message: 'Die Verbindung zum Erstellungsstatus wurde unterbrochen.',
        label: 'Erneut verbinden',
        action: this.reconnect,
        alert: false,
        editable: false,
      };
    }
    return null;
  });
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');

  focusHeading(): void {
    this.heading()?.nativeElement.focus();
  }
}
