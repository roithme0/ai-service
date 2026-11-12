import { Component, inject, OnDestroy, signal } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import {
  HttpImageGenerationTransport,
  ImageGenerationController,
  type ImageGenerationState,
} from '@roithme0/image-generation/controller';
import {
  ImageGenerationUiComponent,
  type ImageGenerationActions,
  type ImageGenerationActionError,
} from '@roithme0/image-generation/ui';
import { DemoHeader } from '../../components/demo-header/demo-header.component';

@Component({
  selector: 'app-image-generation-live-demo',
  imports: [DemoHeader, ImageGenerationUiComponent],
  templateUrl: './image-generation-live-demo.component.html',
  styleUrl: './image-generation-live-demo.component.scss',
})
export class ImageGenerationLiveDemo implements OnDestroy {
  private readonly controller = new ImageGenerationController(
    new HttpImageGenerationTransport('/api/v1', 'demo:default'),
    (state) => this.state.set(state),
  );
  private readonly snackBar = inject(MatSnackBar);

  protected readonly actions: ImageGenerationActions = {
    submit: (instructions) => this.controller.submit(instructions),
    recoverSubmission: () => this.controller.recoverSubmission(),
    reconnect: () => this.controller.reconnect(),
    loadContent: () => this.controller.loadContent(),
  };

  protected readonly state = signal<Readonly<ImageGenerationState>>(this.controller.state);

  protected showActionError(error: ImageGenerationActionError): void {
    this.snackBar.open(error.message, 'OK', { duration: 6000, politeness: 'assertive' });
  }

  ngOnDestroy(): void {
    this.controller.dispose();
  }
}
