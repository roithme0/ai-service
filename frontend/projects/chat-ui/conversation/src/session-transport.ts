import type { ZodType } from 'zod';
import {
  zTurnAccepted,
  zBoundaryError,
  zSessionCreated,
  zSessionCreationRequest,
  zSessionEvent,
  zPresentedSession,
  zHttpValidationError,
} from '../generated/zod.gen';
import type {
  BoundaryError,
  TurnAccepted,
  SessionCreated,
  SessionCreationRequest,
  SessionEvent,
  PresentedSession,
} from '../generated/types.gen';

export type SessionErrorKind = BoundaryError['kind'] | 'validation_error' | 'method_not_allowed';

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
    if (!response.ok) await throwHttpError(response);
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
    if (!response.ok) await throwHttpError(response);
    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      throw new SessionTransportError('invalid_response', { cause: error });
    }
    if (response.status !== status) throw new SessionTransportError('invalid_response');
    return payload;
  }
}

async function* readSseData(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const frameParts: string[] = [];
  let pendingNewline = false;
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
        decoded = decoded.replace(/\r\n?/g, '\n');
      }
      const text: string = pendingNewline ? `\n${decoded}` : decoded;
      let start = 0;
      let end: number;
      while ((end = text.indexOf('\n\n', start)) !== -1) {
        frameParts.push(text.slice(start, end));
        const frame = frameParts.join('');
        frameParts.length = 0;
        start = end + 2;
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, ''))
          .join('\n');
        if (data !== '') yield data;
      }
      pendingNewline = start < text.length && text.endsWith('\n');
      const remainder = text.slice(start, pendingNewline ? -1 : undefined);
      if (remainder !== '') frameParts.push(remainder);
      if (chunk.done) {
        if (frameParts.join('').trim() !== '') throw new SessionTransportError('invalid_response');
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

async function throwHttpError(response: Response): Promise<never> {
  const status = response.status;
  if (status === 405) {
    await response.body?.cancel();
    throw new SessionHttpError(status, 'method_not_allowed');
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error: unknown) {
    throw new SessionTransportError('invalid_response', { cause: error });
  }
  if (status === 422) {
    parse(zHttpValidationError, payload);
    throw new SessionHttpError(status, 'validation_error');
  }
  throw new SessionHttpError(status, parse(zBoundaryError, payload).kind);
}
