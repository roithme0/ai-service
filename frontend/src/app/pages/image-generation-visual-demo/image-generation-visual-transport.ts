import {
  TransportError,
  type ImageEvent,
  type ImageGenerationTransport,
  type Snapshot,
} from '@roithme0/image-generation/controller';
import { IMAGE_GENERATION_VISUAL_TIMINGS as timings } from './image-generation-visual-timings';

export type ImageGenerationVisualScenario =
  | 'success'
  | 'generation-failure'
  | 'connection-lost'
  | 'submission-uncertain'
  | 'image-load-failure';

type Generation = {
  instructions: string;
  snapshot: Snapshot;
  observationLost: boolean;
  contentFailed: boolean;
  uncertain: boolean;
};

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, ms);
    function abort(): void {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(new DOMException('Aborted', 'AbortError'));
    }
    signal.addEventListener('abort', abort, { once: true });
  });
}

export class ImageGenerationVisualTransport implements ImageGenerationTransport {
  private readonly generations = new Map<string, Generation>();
  private readonly keys = new Map<string, Generation>();

  constructor(private readonly scenario: ImageGenerationVisualScenario) {}

  private generation(id: string): Generation {
    const generation = this.generations.get(id);
    if (!generation) throw new TransportError('unavailable', 'Unknown generation');
    return generation;
  }

  private complete(generation: Generation): Snapshot {
    if (generation.snapshot.status !== 'running') return generation.snapshot;
    const running = generation.snapshot;
    generation.snapshot = {
      ...running,
      status: 'completed',
      completed_at: new Date().toISOString(),
      estimated_cost_usd: '0.00',
      content: {
        media_type: 'image/png',
        size_bytes: 3093259,
        url: '/images/image-generation-visual-demo.png',
      },
    };
    return generation.snapshot;
  }

  async submit(instructions: string, key: string, signal: AbortSignal): Promise<Snapshot> {
    const existing = this.keys.get(key);
    if (existing && existing.instructions !== instructions)
      throw new TransportError('rejected', 'Submission key conflicts with existing instructions');
    await delay(existing?.uncertain ? timings.recoveryMs : timings.submissionMs, signal);
    if (existing) {
      if (existing.uncertain) {
        existing.uncertain = false;
        return this.complete(existing);
      }
      return existing.snapshot;
    }
    const admitted = this.keys.get(key);
    if (admitted) {
      if (admitted.instructions !== instructions)
        throw new TransportError('rejected', 'Submission key conflicts with existing instructions');
      if (admitted.uncertain) throw new TransportError('uncertain', 'Could not confirm submission');
      return admitted.snapshot;
    }
    const id = crypto.randomUUID();
    const generation: Generation = {
      instructions,
      observationLost: false,
      contentFailed: false,
      uncertain: this.scenario === 'submission-uncertain',
      snapshot: {
        generation_id: id,
        status: 'running',
        created_at: new Date().toISOString(),
        completed_at: null,
        configured_model: 'Demo-Modell',
        provider_model: null,
        estimated_cost_usd: null,
      },
    };
    this.keys.set(key, generation);
    this.generations.set(id, generation);
    if (generation.uncertain) throw new TransportError('uncertain', 'Could not confirm submission');
    return generation.snapshot;
  }

  async read(id: string, signal: AbortSignal): Promise<Snapshot> {
    await Promise.resolve();
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    return this.generation(id).snapshot;
  }

  async *observe(id: string, signal: AbortSignal): AsyncGenerator<ImageEvent> {
    const generation = this.generation(id);
    if (generation.snapshot.status !== 'running') {
      yield { kind: 'snapshot', snapshot: generation.snapshot };
      return;
    }
    await delay(generation.observationLost ? timings.recoveryMs : timings.generationMs, signal);
    if (generation.snapshot.status !== 'running') {
      yield { kind: 'snapshot', snapshot: generation.snapshot };
      return;
    }
    if (this.scenario === 'connection-lost' && !generation.observationLost) {
      generation.observationLost = true;
      throw new TransportError('observation', 'Connection lost');
    }
    if (this.scenario === 'generation-failure') {
      generation.snapshot = {
        ...generation.snapshot,
        status: 'failed',
        completed_at: new Date().toISOString(),
        error: {
          kind: 'image_generation_failed',
          detail:
            'Die Bilderstellung in der Demo ist fehlgeschlagen. Passe die Beschreibung an und versuche es erneut.',
        },
      };
    } else {
      this.complete(generation);
    }
    yield { kind: 'snapshot', snapshot: generation.snapshot };
  }

  async content(id: string, signal: AbortSignal): Promise<Blob> {
    const generation = this.generation(id);
    if (generation.snapshot.status !== 'completed')
      throw new TransportError('content', 'Image is not ready');
    await delay(timings.imageLoadingMs, signal);
    if (this.scenario === 'image-load-failure' && !generation.contentFailed) {
      generation.contentFailed = true;
      throw new TransportError('content', 'Demo image could not be loaded');
    }
    try {
      const response = await fetch('/images/image-generation-visual-demo.png', { signal });
      if (!response.ok) throw new Error('Image unavailable');
      const blob = await response.blob();
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      if (blob.type !== 'image/png' || blob.size !== generation.snapshot.content.size_bytes)
        throw new Error('Unexpected image content');
      return blob;
    } catch (error: unknown) {
      if (signal.aborted) throw error;
      throw new TransportError('content', 'Demo image could not be loaded');
    }
  }
}
