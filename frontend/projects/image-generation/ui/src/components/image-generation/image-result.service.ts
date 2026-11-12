import { Injectable, OnDestroy, signal } from '@angular/core';
import type { CompletedSnapshot, ImageContent } from '@roithme0/image-generation/controller';

export type ImageResult = ImageContent & { instructions: string; url: string };

@Injectable()
export class ImageResultService implements OnDestroy {
  private readonly resultState = signal<ImageResult | null>(null);
  private readonly loadingState = signal(false);
  private readonly errorState = signal<string | null>(null);

  readonly result = this.resultState.asReadonly();
  readonly loading = this.loadingState.asReadonly();
  readonly error = this.errorState.asReadonly();

  private requested: string | null = null;
  private epoch = 0;
  private destroyed = false;

  hasRequested(generationId: string): boolean {
    return this.requested === generationId;
  }

  async load(
    snapshot: CompletedSnapshot,
    instructions: string,
    loadContent: () => Promise<ImageContent>,
  ): Promise<void> {
    if (this.loading()) return;
    this.requested = snapshot.generation_id;
    this.loadingState.set(true);
    this.errorState.set(null);
    const epoch = this.epoch;
    try {
      const content = await loadContent();
      if (this.destroyed || epoch !== this.epoch) return;
      if (
        content.snapshot.generation_id !== snapshot.generation_id ||
        content.blob.type !== 'image/png' ||
        !content.blob.size
      )
        throw new Error('Invalid image content');
      const url = URL.createObjectURL(content.blob);
      this.resultState.set({ ...content, instructions, url });
    } catch {
      if (!this.destroyed && epoch === this.epoch)
        this.errorState.set('Das Bild konnte nicht geladen werden.');
    } finally {
      if (!this.destroyed && epoch === this.epoch) this.loadingState.set(false);
    }
  }

  imageError(): void {
    const result = this.result();
    if (result) URL.revokeObjectURL(result.url);
    this.resultState.set(null);
    this.errorState.set('Das Bild konnte nicht angezeigt werden.');
  }

  clear(): void {
    this.epoch++;
    const result = this.result();
    if (result) URL.revokeObjectURL(result.url);
    this.resultState.set(null);
    this.requested = null;
    this.loadingState.set(false);
    this.errorState.set(null);
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clear();
  }
}
