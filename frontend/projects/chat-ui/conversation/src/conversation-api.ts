import type {
  CompletedTurnResponse,
  SessionCreationResponse,
  SessionSnapshotResponse,
  UserMessageResponse,
} from '../generated/types.gen';
import {
  zCompletedTurnResponse,
  zSessionCreationResponse,
  zSessionSnapshotResponse,
  zUserMessageResponse,
} from '../generated/zod.gen';
import type { ZodType } from 'zod';

export const AgentConfiguration = { Demo: 'demo', Kochwiki: 'kochwiki' } as const;
export type AgentConfiguration = (typeof AgentConfiguration)[keyof typeof AgentConfiguration];

export type ApiMessage = SessionSnapshotResponse['messages'][number];

export class ConversationApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: string,
  ) {
    super(`Conversation request failed: ${status} ${kind}`);
  }
}

export class ConversationNetworkError extends Error {}

export interface ConversationTransport {
  createSession(): Promise<SessionCreationResponse>;
  readSession(sessionId: string): Promise<SessionSnapshotResponse>;
  appendMessage(sessionId: string, text: string): Promise<UserMessageResponse>;
  generateTurn(sessionId: string): Promise<CompletedTurnResponse>;
}

export class HttpConversationTransport implements ConversationTransport {
  private readonly baseUrl: string;

  constructor(apiBaseUrl: string, configuration: AgentConfiguration, private readonly input: unknown = {}) {
    this.baseUrl = `${apiBaseUrl.replace(/\/+$/, '')}/agents/${encodeURIComponent(configuration)}/sessions`;
  }

  async createSession(): Promise<SessionCreationResponse> {
    return parseResponse(zSessionCreationResponse, await this.request('', 'POST', { input: this.input }));
  }

  async readSession(sessionId: string): Promise<SessionSnapshotResponse> {
    return parseResponse(zSessionSnapshotResponse, await this.request(`/${sessionId}`, 'GET'));
  }

  async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    return parseResponse(zUserMessageResponse, await this.request(`/${sessionId}/messages`, 'POST', { text }));
  }

  async generateTurn(sessionId: string): Promise<CompletedTurnResponse> {
    return parseResponse(zCompletedTurnResponse, await this.request(`/${sessionId}/turns`, 'POST'));
  }

  private async request(path: string, method: 'GET' | 'POST', body?: object): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
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
      throw new ConversationApiError(response.status, readString(payload, 'kind') ?? 'unknown_error');
    }
    return payload;
  }
}

function parseResponse<T>(schema: ZodType<T>, value: unknown): T {
  const result = schema.safeParse(value);
  if (!result.success) throw invalidResponse();
  return result.data;
}

function readString(value: unknown, key: string): string | null {
  if (!isRecord(value)) return null;
  const field = value[key];
  return typeof field === 'string' ? field : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidResponse(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
