import {
  zSnapshot,
  zImageEvent,
  zRequestValidationErrorResponse,
  zErrorEnvelopeLiteralImageGenerationUnavailableImageGenerationIdempotencyConflictImageGenerationNotCompleted,
} from './generated/zod.gen';
import type { ImageEvent, Snapshot } from './generated/types.gen';
import { z } from 'zod';
export type { ImageEvent, Snapshot } from './generated/types.gen';

export interface ImageGenerationTransport {
  submit(instructions: string, key: string, signal: AbortSignal): Promise<Snapshot>;
  read(id: string, signal: AbortSignal): Promise<Snapshot>;
  observe(id: string, signal: AbortSignal): AsyncGenerator<ImageEvent>;
  content(id: string, signal: AbortSignal): Promise<Blob>;
}
export class TransportError extends Error {
  constructor(
    public readonly category: 'uncertain' | 'rejected' | 'unavailable' | 'observation' | 'content',
    message: string,
  ) {
    super(message);
  }
}

function snapshot(value: unknown, id?: string): Snapshot {
  const result = zSnapshot.parse(value);
  if (id && result.generation_id.toLowerCase() !== id.toLowerCase())
    throw new Error('Unexpected generation ID');
  return result;
}

function media(response: Response, expected: string): boolean {
  return response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() === expected;
}

async function* eventLines(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  try {
    while (true) {
      const part = await reader.read();
      buffer += decoder.decode(part.value, { stream: !part.done });
      let match: RegExpExecArray | null;
      while ((match = /\r\n|\r|\n/.exec(buffer)) !== null) {
        if (match[0] === '\r' && match.index === buffer.length - 1 && !part.done) break;
        const line = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        yield line;
      }
      if (part.done) throw new Error('Incomplete observation');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function eventData(line: string): string {
  const separator = line.indexOf(':');
  const field = separator < 0 ? line : line.slice(0, separator);
  if (field !== 'data') throw new Error('Unsupported SSE field');
  const value = separator < 0 ? '' : line.slice(separator + 1);
  return value.startsWith(' ') ? value.slice(1) : value;
}

export class HttpImageGenerationTransport implements ImageGenerationTransport {
  private readonly base: string;
  private readonly fetcher: typeof fetch;
  constructor(
    baseUrl: string,
    private readonly applicationUser: string,
    fetcher?: typeof fetch,
  ) {
    this.base = baseUrl.replace(/\/+$/, '');
    this.fetcher = fetcher ?? globalThis.fetch.bind(globalThis);
  }

  private url(id = ''): string {
    if (id) z.uuid().parse(id);
    return `${this.base}/image-generations${id ? `/${encodeURIComponent(id)}` : ''}`;
  }

  private headers(extra: Record<string, string> = {}): HeadersInit {
    return { 'X-Application-User': this.applicationUser, ...extra };
  }

  async submit(instructions: string, key: string, signal: AbortSignal): Promise<Snapshot> {
    let response: Response;
    try {
      response = await this.fetcher(this.url(), {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/json', 'Idempotency-Key': key }),
        body: JSON.stringify({ instructions }),
        signal,
      });
    } catch (error: unknown) {
      if (signal.aborted) throw error;
      throw new TransportError('uncertain', 'Could not confirm submission');
    }
    try {
      if (!media(response, 'application/json')) throw new Error('Invalid media type');
      const value: unknown = await response.json();
      if (response.status === 200 || response.status === 202) return snapshot(value);
      const documented =
        zErrorEnvelopeLiteralImageGenerationUnavailableImageGenerationIdempotencyConflictImageGenerationNotCompleted.safeParse(
          value,
        );
      if (
        response.status === 503 &&
        documented.success &&
        documented.data.kind === 'image_generation_unavailable'
      )
        throw new TransportError('rejected', documented.data.detail);
      if (
        response.status === 409 &&
        documented.success &&
        documented.data.kind === 'image_generation_idempotency_conflict'
      )
        throw new TransportError('rejected', documented.data.detail);
      if (response.status === 422 && zRequestValidationErrorResponse.safeParse(value).success)
        throw new TransportError('rejected', 'Invalid request');
      throw new Error('Unrecognized admission response');
    } catch (error: unknown) {
      if (signal.aborted || error instanceof TransportError) throw error;
      throw new TransportError('uncertain', 'Could not confirm submission');
    }
  }

  async read(id: string, signal: AbortSignal): Promise<Snapshot> {
    try {
      const response = await this.fetcher(this.url(id), { headers: this.headers(), signal });
      if (response.status !== 200 || !media(response, 'application/json'))
        throw new Error('Invalid status response');
      return snapshot(await response.json(), id);
    } catch (error: unknown) {
      if (signal.aborted) throw error;
      throw new TransportError('unavailable', 'Status unavailable');
    }
  }

  async *observe(id: string, signal: AbortSignal): AsyncGenerator<ImageEvent> {
    try {
      const response = await this.fetcher(`${this.url(id)}/events`, {
        headers: this.headers({ Accept: 'text/event-stream' }),
        signal,
      });
      if (response.status !== 200 || !media(response, 'text/event-stream') || !response.body)
        throw new TransportError('observation', 'Observation unavailable');
      let data: string[] = [];
      for await (const line of eventLines(response.body)) {
        if (line.startsWith(':')) continue;
        if (line) {
          data.push(eventData(line));
          continue;
        }
        if (!data.length) continue;
        const event = zImageEvent.parse(JSON.parse(data.join('\n')) as unknown);
        data = [];
        if (event.kind === 'snapshot') snapshot(event.snapshot, id);
        const terminal = event.kind === 'error' || event.snapshot.status !== 'running';
        yield event;
        if (terminal) return;
      }
    } catch (error: unknown) {
      if (signal.aborted) throw error;
      throw new TransportError('observation', 'Observation unavailable');
    }
  }

  async content(id: string, signal: AbortSignal): Promise<Blob> {
    try {
      const response = await this.fetcher(`${this.url(id)}/content`, {
        headers: this.headers({ Accept: 'image/png' }),
        signal,
      });
      if (response.status !== 200 || !media(response, 'image/png'))
        throw new Error('Invalid content response');
      const blob = await response.blob();
      if (!blob.size) throw new Error('Empty content');
      return blob;
    } catch (error: unknown) {
      if (signal.aborted) throw error;
      throw new TransportError('content', 'Content unavailable');
    }
  }
}
