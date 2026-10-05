import type {
  AppendMessageApiV1AgentsConfigurationSessionsSessionIdMessagesPostData,
  AcceptedTurnResponse,
  StreamEvent,
  CreateSessionApiV1AgentsConfigurationSessionsPostData,
  ErrorResponse,
  SessionCreationResponse,
  SessionSnapshotResponse,
  UserMessageResponse,
  ValidationErrorResponse,
} from '../generated/types.gen';
import {
  zAcceptedTurnResponse,
  zStreamEvent,
  zCreateSessionApiV1AgentsConfigurationSessionsPostPath,
  zErrorResponse,
  zSessionCreationResponse,
  zSessionSnapshotResponse,
  zUserMessageResponse,
  zValidationDetail,
  zValidationErrorResponse,
} from '../generated/zod.gen';
import { z, type ZodType } from 'zod';

const validationDetailSchema = z.strictObject(zValidationDetail.shape);
const errorResponseSchema = z.union([
  z.strictObject(zErrorResponse.shape),
  z.strictObject({
    ...zValidationErrorResponse.shape,
    detail: z.array(validationDetailSchema).min(1),
  }),
]);

export const AgentConfiguration =
  zCreateSessionApiV1AgentsConfigurationSessionsPostPath.shape.configuration.enum;
export type AgentConfiguration =
  CreateSessionApiV1AgentsConfigurationSessionsPostData['path']['configuration'];

export type ApiMessage = SessionSnapshotResponse['messages'][number];
export type ApiErrorKind = ErrorResponse['kind'] | ValidationErrorResponse['kind'];

export class ConversationApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: ApiErrorKind,
  ) {
    super(`Conversation request failed: ${status} ${kind}`);
  }
}

export class ConversationNetworkError extends Error {}

export interface ConversationTransport {
  createSession(): Promise<SessionCreationResponse>;
  readSession(sessionId: string): Promise<SessionSnapshotResponse>;
  appendMessage(sessionId: string, text: string): Promise<UserMessageResponse>;
  generateTurn(sessionId: string): Promise<AcceptedTurnResponse>;
  observeTurn(sessionId: string, turnId: string, signal: AbortSignal): AsyncIterable<StreamEvent>;
}

export class HttpConversationTransport implements ConversationTransport {
  private readonly baseUrl: string;

  constructor(
    apiBaseUrl: string,
    configuration: AgentConfiguration,
    private readonly applicationUser: string,
    private readonly input: unknown = {},
  ) {
    this.baseUrl = `${apiBaseUrl.replace(/\/+$/, '')}/agents/${encodeURIComponent(configuration)}/sessions`;
  }

  async createSession(): Promise<SessionCreationResponse> {
    const body = {
      input: this.input,
    } satisfies CreateSessionApiV1AgentsConfigurationSessionsPostData['body'];
    return parseResponse(zSessionCreationResponse, await this.request('', 'POST', body));
  }

  async readSession(sessionId: string): Promise<SessionSnapshotResponse> {
    return parseResponse(zSessionSnapshotResponse, await this.request(`/${sessionId}`, 'GET'));
  }

  async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    const body = {
      text,
    } satisfies AppendMessageApiV1AgentsConfigurationSessionsSessionIdMessagesPostData['body'];
    return parseResponse(
      zUserMessageResponse,
      await this.request(`/${sessionId}/messages`, 'POST', body),
    );
  }

  async generateTurn(sessionId: string): Promise<AcceptedTurnResponse> {
    return parseResponse(zAcceptedTurnResponse, await this.request(`/${sessionId}/turns`, 'POST'));
  }

  async *observeTurn(
    sessionId: string,
    turnId: string,
    signal: AbortSignal,
  ): AsyncIterable<StreamEvent> {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch(
        `${this.baseUrl}/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/events`,
        {
          signal,
          headers: { Accept: 'text/event-stream', 'X-Application-User': this.applicationUser },
        },
      );
      if (!response.ok) {
        const error = parseResponse(errorResponseSchema, await response.json());
        throw new ConversationApiError(response.status, error.kind);
      }
      if (
        !response.headers.get('Content-Type')?.startsWith('text/event-stream') ||
        response.body === null
      )
        throw invalidResponse();
      reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8', { fatal: true });
      let buffer = '';
      let scanFrom = 0;
      let pendingCarriageReturn = false;
      while (true) {
        const chunk = await reader.read();
        let decoded = decoder.decode(chunk.value, { stream: !chunk.done });
        if (decoded !== '') {
          const endedWithCarriageReturn = decoded.endsWith('\r');
          if (pendingCarriageReturn && decoded.startsWith('\n')) decoded = decoded.slice(1);
          pendingCarriageReturn = endedWithCarriageReturn;
          buffer += decoded.replace(/\r\n?/g, '\n');
        }
        let end: number;
        while ((end = buffer.indexOf('\n\n', scanFrom)) !== -1) {
          const frame = buffer.slice(0, end);
          buffer = buffer.slice(end + 2);
          scanFrom = 0;
          const data = frame
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).replace(/^ /, ''))
            .join('\n');
          if (data === '') continue;
          yield parseResponse(zStreamEvent, JSON.parse(data) as unknown);
        }
        scanFrom = Math.max(0, buffer.length - 1);
        if (chunk.done) return;
      }
    } catch (error: unknown) {
      if (error instanceof ConversationApiError || error instanceof ConversationNetworkError)
        throw error;
      throw new ConversationNetworkError('Die Beobachtung der Antwort wurde unterbrochen.', {
        cause: error,
      });
    } finally {
      if (reader !== undefined) {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    }
  }

  private async request(path: string, method: 'GET' | 'POST', body?: object): Promise<unknown> {
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
      throw new ConversationNetworkError('Der Backend-Dienst ist nicht erreichbar.', {
        cause: error,
      });
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      throw new ConversationNetworkError('Die Antwort des Backend-Dienstes war unvollständig.', {
        cause: error,
      });
    }
    if (!response.ok) {
      const errorBody = parseResponse(errorResponseSchema, payload);
      throw new ConversationApiError(response.status, errorBody.kind);
    }
    return payload;
  }
}

function parseResponse<T>(schema: ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);
  if (!result.success) throw invalidResponse();
  return result.data;
}

function invalidResponse(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
