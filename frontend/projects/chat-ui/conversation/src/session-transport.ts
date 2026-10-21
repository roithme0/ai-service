import type { ZodType } from 'zod';
import {
  zTurnAccepted,
  zBoundaryError,
  zSessionCreated,
  zSessionCreationRequest,
  zSessionEvent,
  zPresentedSession,
  zHttpValidationError,
} from '../generated/native/zod.gen';
import type {
  BoundaryError,
  TurnAccepted,
  SessionCreated,
  SessionCreationRequest,
  SessionEvent,
  PresentedSession,
} from '../generated/native/types.gen';

export type SessionErrorKind = BoundaryError['kind'] | 'validation_error';

export class SessionHttpError extends Error {
  constructor(
    readonly status: number,
    readonly kind: SessionErrorKind,
  ) {
    super(`Session request failed: ${status} ${kind}`);
  }
}

export class SessionTransportError extends Error {
  constructor(
    readonly reason: 'network' | 'invalid_response',
    options?: ErrorOptions,
  ) {
    super(
      reason === 'network' ? 'Session connection failed.' : 'Invalid session response.',
      options,
    );
  }
}

export interface SessionTransport {
  createSession(initialization?: SessionCreationRequest): Promise<SessionCreated>;
  readSession(sessionId: string): Promise<PresentedSession>;
  submitPrompt(sessionId: string, prompt: string): Promise<TurnAccepted>;
  observeSession(sessionId: string, signal: AbortSignal): AsyncIterable<SessionEvent>;
}

export class HttpSessionTransport implements SessionTransport {
  private readonly baseUrl: string;

  constructor(
    apiBaseUrl: string,
    configuration: string,
    private readonly applicationUser: string,
  ) {
    this.baseUrl = `${apiBaseUrl.replace(/\/+$/, '')}/agents/${encodeURIComponent(configuration)}/sessions`;
  }

  async createSession(initialization: SessionCreationRequest = {}): Promise<SessionCreated> {
    return parse(
      zSessionCreated,
      await this.request('', 'POST', 201, parse(zSessionCreationRequest, initialization)),
    );
  }

  async readSession(sessionId: string): Promise<PresentedSession> {
    const snapshot = parse(
      zPresentedSession,
      await this.request(`/${encodeURIComponent(sessionId)}`, 'GET', 200),
    );
    checkSession(snapshot, sessionId);
    return snapshot;
  }

  async submitPrompt(sessionId: string, prompt: string): Promise<TurnAccepted> {
    return parse(
      zTurnAccepted,
      await this.request(`/${encodeURIComponent(sessionId)}/turns`, 'POST', 202, { prompt }),
    );
  }

  async *observeSession(sessionId: string, signal: AbortSignal): AsyncIterable<SessionEvent> {
    try {
      const body = await this.connectObservation(sessionId, signal);
      for await (const data of readSseData(body)) {
        const event = parseSessionEvent(data, sessionId);
        yield event;
        if (event.kind === 'error') return;
      }
    } catch (error: unknown) {
      signal.throwIfAborted();
      if (error instanceof SessionHttpError || error instanceof SessionTransportError) throw error;
      throw new SessionTransportError('invalid_response', { cause: error });
    }
  }

  private async connectObservation(
    sessionId: string,
    signal: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>> {
    const response = await fetch(`${this.baseUrl}/${encodeURIComponent(sessionId)}/events`, {
      signal,
      headers: { 'X-Application-User': this.applicationUser, Accept: 'text/event-stream' },
    }).catch((error: unknown) => {
      throw new SessionTransportError('network', { cause: error });
    });
    if (!response.ok) throwHttpError(response.status, (await response.json()) as unknown);
    if (
      response.status !== 200 ||
      response.headers.get('Content-Type')?.split(';')[0].trim() !== 'text/event-stream' ||
      response.body === null
    ) {
      await response.body?.cancel();
      throw new SessionTransportError('invalid_response');
    }
    return response.body;
  }

  private async request(
    path: string,
    method: 'GET' | 'POST',
    status: number,
    body?: object,
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          'X-Application-User': this.applicationUser,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error: unknown) {
      throw new SessionTransportError('network', { cause: error });
    }
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      throw new SessionTransportError('invalid_response', { cause: error });
    }
    if (!response.ok) throwHttpError(response.status, payload);
    if (response.status !== status) throw new SessionTransportError('invalid_response');
    return payload;
  }
}

async function* readSseData(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  let pendingCarriageReturn = false;
  try {
    while (true) {
      const chunk = await reader.read().catch((error: unknown) => {
        throw new SessionTransportError('network', { cause: error });
      });
      let decoded = decoder.decode(chunk.value, { stream: !chunk.done });
      if (decoded !== '') {
        const endsWithCarriageReturn = decoded.endsWith('\r');
        if (pendingCarriageReturn && decoded.startsWith('\n')) decoded = decoded.slice(1);
        pendingCarriageReturn = endsWithCarriageReturn;
        buffer += decoded.replace(/\r\n?/g, '\n');
      }
      let end: number;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, ''))
          .join('\n');
        if (data !== '') yield data;
      }
      if (chunk.done) {
        if (buffer.trim() !== '') throw new SessionTransportError('invalid_response');
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function parseSessionEvent(data: string, sessionId: string): SessionEvent {
  const event = parse(zSessionEvent, JSON.parse(data) as unknown);
  if (event.kind === 'snapshot') checkSession(event.snapshot, sessionId);
  return event;
}

function parse<T>(schema: ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);
  if (!result.success) throw new SessionTransportError('invalid_response');
  return result.data;
}

function checkSession(snapshot: PresentedSession, sessionId: string): void {
  if (snapshot.session_id !== sessionId) throw new SessionTransportError('invalid_response');
}

function throwHttpError(status: number, payload: unknown): never {
  if (status === 422) {
    parse(zHttpValidationError, payload);
    throw new SessionHttpError(status, 'validation_error');
  }
  throw new SessionHttpError(status, parse(zBoundaryError, payload).kind);
}
