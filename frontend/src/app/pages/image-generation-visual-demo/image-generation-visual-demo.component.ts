import {
  AfterViewInit,
  Component,
  signal,
  TemplateRef,
  viewChild,
  ViewContainerRef,
} from '@angular/core';
import { MatRadioModule } from '@angular/material/radio';
import { DemoHeader } from '../../components/demo-header/demo-header.component';
import { SectionNavComponent } from '../../components/section-nav/section-nav.component';
import type { ImageGenerationInstructionMode } from '@roithme0/image-generation/ui';
import type { ImageGenerationVisualScenario } from './image-generation-visual-transport';
import {
  ImageGenerationVisualRun,
  type DemoActionOutcome,
} from './image-generation-visual-run.component';

@Component({
  selector: 'app-image-generation-visual-demo',
  imports: [DemoHeader, SectionNavComponent, MatRadioModule, ImageGenerationVisualRun],
  templateUrl: './image-generation-visual-demo.component.html',
  styleUrl: './image-generation-visual-demo.component.scss',
})
export class ImageGenerationVisualDemo implements AfterViewInit {
  protected readonly scenarios: readonly { id: ImageGenerationVisualScenario; label: string }[] = [
    { id: 'success', label: 'Erfolg' },
    { id: 'generation-failure', label: 'Bilderstellung fehlgeschlagen' },
    { id: 'connection-lost', label: 'Verbindung unterbrochen' },
    { id: 'submission-rejected', label: 'Absenden abgelehnt' },
    { id: 'submission-uncertain', label: 'Absenden unbestätigt' },
    { id: 'image-load-failure', label: 'Bild konnte nicht geladen werden' },
  ];
  protected readonly scenario = signal<ImageGenerationVisualScenario>('success');
  protected readonly instructionMode = signal<ImageGenerationInstructionMode>('editable');
  protected readonly outcome = signal<DemoActionOutcome>('success');
  private readonly runTemplate = viewChild.required<TemplateRef<unknown>>('runTemplate');
  private readonly runHost = viewChild.required('runHost', { read: ViewContainerRef });

  ngAfterViewInit(): void {
    this.runHost().createEmbeddedView(this.runTemplate());
  }

  protected selectScenario(id: string): void {
    const next = this.scenarios.find((item) => item.id === id);
    if (!next) return;
    this.scenario.set(next.id);
    this.replaceRun();
  }

  protected selectInstructionMode(mode: ImageGenerationInstructionMode): void {
    if (mode === this.instructionMode()) return;
    this.instructionMode.set(mode);
    this.replaceRun();
  }

  private replaceRun(): void {
    this.runHost().clear();
    this.runHost().createEmbeddedView(this.runTemplate());
  }
}
