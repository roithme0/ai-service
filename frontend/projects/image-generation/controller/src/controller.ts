import type { ImageEvent, ImageGenerationTransport, Snapshot } from './transport';
import type { CompletedSnapshot } from './generated/types.gen';
import { TransportError } from './transport';

export type Admission = 'idle' | 'submitting' | 'uncertain' | 'rejected' | 'accepted';
export type Observation = 'idle' | 'observing' | 'lost';
export type ContentState = 'idle' | 'loading' | 'ready' | 'error';
export interface ImageGenerationState {
  admission: Admission;
  instructions: string | null;
  snapshot: Snapshot | null;
  observation: Observation;
  content: ContentState;
  error: string | null;
}

export interface ImageContent {
  blob: Blob;
  filename: string;
  snapshot: CompletedSnapshot;
}

export class InvalidStateError extends Error {}

export class ImageGenerationController {
  private current: ImageGenerationState = {
    admission: 'idle',
    instructions: null,
    snapshot: null,
    observation: 'idle',
    content: 'idle',
    error: null,
  };
  private key: string | null = null;
  private disposed = false;
  private epoch = 0;
  private requests = new Set<AbortController>();
  private observation: AbortController | null = null;
  private reading = false;
  private loading = false;
  constructor(
    private readonly transport: ImageGenerationTransport,
    private readonly publish: (state: Readonly<ImageGenerationState>) => void,
  ) {}

  get state(): Readonly<ImageGenerationState> {
    return this.current;
  }

  private set(change: Partial<ImageGenerationState>): void {
    if (!this.disposed) {
      this.current = { ...this.current, ...change };
      this.publish(this.current);
    }
  }

  private active(): void {
    if (this.disposed) throw new InvalidStateError('Controller is disposed');
  }

  private request(): AbortController {
    const request = new AbortController();
    this.requests.add(request);
    return request;
  }

  private apply(next: Snapshot): void {
    const old = this.current.snapshot;
    if (old && old.generation_id !== next.generation_id)
      throw new Error('Unexpected generation ID');
    if (old && old.status !== 'running') {
      if (next.status === 'running' || JSON.stringify(old) !== JSON.stringify(next))
        throw new Error('Conflicting terminal snapshot');
      return;
    }
    this.set({ snapshot: next });
    if (next.status !== 'running') {
      this.observation?.abort();
      this.observation = null;
      this.set({ observation: 'idle' });
    }
  }

  async submit(instructions: string): Promise<void> {
    this.active();
    if (
      this.current.admission === 'submitting' ||
      this.current.admission === 'uncertain' ||
      this.current.snapshot?.status === 'running'
    )
      throw new InvalidStateError('A generation is active');
    if (!instructions.trim() || [...instructions].length > 32000)
      throw new InvalidStateError('Invalid instructions');
    this.epoch++;
    this.observation?.abort();
    this.key = crypto.randomUUID();
    this.set({
      admission: 'submitting',
      instructions,
      snapshot: null,
      observation: 'idle',
      content: 'idle',
      error: null,
    });
    await this.admit();
  }

  async recoverSubmission(): Promise<void> {
    this.active();
    if (this.current.admission !== 'uncertain')
      throw new InvalidStateError('No uncertain submission');
    this.set({ admission: 'submitting', error: null });
    await this.admit();
  }

  private async admit(): Promise<void> {
    if (this.disposed) return;
    const epoch = this.epoch;
    const request = this.request();
    try {
      const result = await this.transport.submit(
        this.current.instructions!,
        this.key!,
        request.signal,
      );
      if (this.disposed || epoch !== this.epoch) return;
      this.set({ admission: 'accepted', snapshot: result, error: null });
      if (!this.disposed && epoch === this.epoch && result.status === 'running')
        this.startObservation(result.generation_id);
    } catch (error: unknown) {
      if (this.disposed || epoch !== this.epoch) return;
      const rejected = error instanceof TransportError && error.category === 'rejected';
      this.set({
        admission: rejected ? 'rejected' : 'uncertain',
        error: error instanceof Error ? error.message : 'Submission failed',
      });
    } finally {
      this.requests.delete(request);
    }
  }

  private startObservation(id: string): void {
    this.observation?.abort();
    const request = this.request();
    this.observation = request;
    const epoch = this.epoch;
    this.set({ observation: 'observing' });
    if (this.disposed || epoch !== this.epoch) {
      request.abort();
      this.requests.delete(request);
      return;
    }

    void (async () => {
      try {
        for await (const event of this.transport.observe(id, request.signal)) {
          if (this.disposed || epoch !== this.epoch || this.observation !== request) return;
          this.applyEvent(event);
          if (event.kind === 'snapshot' && event.snapshot.status !== 'running') return;
        }
        if (!request.signal.aborted) throw new Error('Observation ended');
      } catch {
        if (
          !this.disposed &&
          epoch === this.epoch &&
          this.observation === request &&
          !request.signal.aborted
        )
          this.set({ observation: 'lost' });
      } finally {
        this.requests.delete(request);
        if (this.observation === request) this.observation = null;
      }
    })();
  }

  private applyEvent(event: ImageEvent): void {
    if (event.kind === 'error') throw new Error('Observation failed');
    this.apply(event.snapshot);
  }

  reconnect(): void {
    this.active();
    const s = this.current.snapshot;
    if (!s || s.status !== 'running' || this.current.observation === 'observing')
      throw new InvalidStateError('Cannot reconnect');
    this.startObservation(s.generation_id);
  }

  async readStatus(): Promise<void> {
    this.active();
    const s = this.current.snapshot;
    if (!s || this.reading) throw new InvalidStateError('Cannot read status');
    this.reading = true;
    const request = this.request();
    const epoch = this.epoch;
    try {
      const next = await this.transport.read(s.generation_id, request.signal);
      if (!this.disposed && epoch === this.epoch) this.apply(next);
    } finally {
      this.reading = false;
      this.requests.delete(request);
    }
  }

  async loadContent(): Promise<ImageContent> {
    this.active();
    const s = this.current.snapshot;
    if (!s || s.status !== 'completed' || this.loading)
      throw new InvalidStateError('Content unavailable');
    this.loading = true;
    const request = this.request();
    const epoch = this.epoch;
    this.set({ content: 'loading' });
    try {
      if (this.disposed || epoch !== this.epoch)
        throw new InvalidStateError('Operation superseded');
      const blob = await this.transport.content(s.generation_id, request.signal);
      if (this.disposed || epoch !== this.epoch)
        throw new InvalidStateError('Operation superseded');
      this.set({ content: 'ready' });
      return { blob, filename: `${s.generation_id}.png`, snapshot: s };
    } catch (error: unknown) {
      if (!this.disposed && epoch === this.epoch) this.set({ content: 'error' });
      throw error;
    } finally {
      this.loading = false;
      this.requests.delete(request);
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.epoch++;
    for (const request of this.requests) request.abort();
    this.requests.clear();
    this.observation = null;
    this.key = null;
    this.current = {
      admission: 'idle',
      instructions: null,
      snapshot: null,
      observation: 'idle',
      content: 'idle',
      error: null,
    };
  }
}
