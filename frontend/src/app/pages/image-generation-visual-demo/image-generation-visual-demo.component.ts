import { Component, signal, viewChild } from '@angular/core';
import { MatRadioModule } from '@angular/material/radio';
import { DemoHeader } from '../../components/demo-header/demo-header.component';
import { SectionNavComponent } from '../../components/section-nav/section-nav.component';
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
export class ImageGenerationVisualDemo {
  protected readonly scenarios: readonly { id: ImageGenerationVisualScenario; label: string }[] = [
    { id: 'success', label: 'Success' },
    { id: 'generation-failure', label: 'Generation failure' },
    { id: 'connection-lost', label: 'Connection lost' },
    { id: 'submission-uncertain', label: 'Submission uncertain' },
    { id: 'image-load-failure', label: 'Image load failure' },
  ];
  protected readonly scenario = signal<ImageGenerationVisualScenario>('success');
  protected readonly outcome = signal<DemoActionOutcome>('success');
  protected readonly runs = signal<readonly { id: number }[]>([{ id: 0 }]);
  private readonly currentRun = viewChild(ImageGenerationVisualRun);

  protected selectScenario(id: string): void {
    const next = this.scenarios.find((item) => item.id === id);
    if (!next) return;
    this.scenario.set(next.id);
    this.replaceRun();
  }
  private replaceRun(): void {
    this.currentRun()?.dispose();
    this.runs.update(([run]) => [{ id: run.id + 1 }]);
  }
}
