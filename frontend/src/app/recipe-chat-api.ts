import { RECIPE_SESSION_FIXTURE } from './recipe-chat-fixture';

export type ApiMessageRole = 'user' | 'assistant';

export interface ApiMessage {
  readonly role: ApiMessageRole;
  readonly text: string;
}

export interface SessionCreation {
  readonly session_id: string;
  readonly expires_at: string;
}

export interface SessionSnapshot {
  readonly session_id: string;
  readonly messages: readonly ApiMessage[];
  readonly terminal_turn_id: string | null;
  readonly terminal_turn_kind: string | null;
}

export interface TurnResult {
  readonly turn_id: string;
  readonly message: ApiMessage;
}

export interface RecipeSessionRequest {
  readonly source: {
    readonly external_reference: string;
    readonly recipe: {
      readonly name: string;
      readonly servings: number;
      readonly preparation_time: number | null;
      readonly origin_name: string | null;
      readonly origin_url: string | null;
      readonly ingredients: readonly {
        readonly index: number;
        readonly amount: number;
        readonly foodstuff_reference: number;
      }[];
      readonly steps: readonly { readonly index: number; readonly description: string }[];
    };
  };
  readonly foodstuffs: readonly {
    readonly external_reference: number;
    readonly name: string;
    readonly brand: string | null;
    readonly unit: 'G' | 'ML' | 'PIECE';
  }[];
}

export class RecipeChatApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: string,
  ) {
    super(`Recipe chat request failed: ${status} ${kind}`);
  }
}

export class RecipeChatNetworkError extends Error {}

export interface RecipeChatTransport {
  createSession(): Promise<SessionCreation>;
  readSession(sessionId: string): Promise<SessionSnapshot>;
  appendMessage(sessionId: string, text: string): Promise<ApiMessage>;
  generateTurn(sessionId: string): Promise<TurnResult>;
}

export class HttpRecipeChatTransport implements RecipeChatTransport {
  private readonly baseUrl = '/api/v1/recipe-improvement/sessions';

  async createSession(): Promise<SessionCreation> {
    return parseSessionCreation(await this.request('', 'POST', RECIPE_SESSION_FIXTURE));
  }

  async readSession(sessionId: string): Promise<SessionSnapshot> {
    return parseSessionSnapshot(await this.request(`/${sessionId}`, 'GET'));
  }

  async appendMessage(sessionId: string, text: string): Promise<ApiMessage> {
    return parseMessage(await this.request(`/${sessionId}/messages`, 'POST', { text }));
  }

  async generateTurn(sessionId: string): Promise<TurnResult> {
    return parseTurnResult(await this.request(`/${sessionId}/turns`, 'POST'));
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
      throw new RecipeChatNetworkError('Der Backend-Dienst ist nicht erreichbar.', {
        cause: error,
      });
    }

    let payload: unknown;
    try {
      payload = await response.json();
    } catch (error: unknown) {
      throw new RecipeChatNetworkError('Die Antwort des Backend-Dienstes war unvollständig.', {
        cause: error,
      });
    }
    if (!response.ok) {
      throw new RecipeChatApiError(response.status, readString(payload, 'kind') ?? 'unknown_error');
    }
    return payload;
  }
}

function parseSessionCreation(value: unknown): SessionCreation {
  const sessionId = readString(value, 'session_id');
  const expiresAt = readString(value, 'expires_at');
  if (sessionId === null || expiresAt === null) throw invalidResponse();
  return { session_id: sessionId, expires_at: expiresAt };
}

function parseMessage(value: unknown): ApiMessage {
  const role = readString(value, 'role');
  const text = readString(value, 'text');
  if ((role !== 'user' && role !== 'assistant') || text === null) throw invalidResponse();
  return { role, text };
}

function parseSessionSnapshot(value: unknown): SessionSnapshot {
  if (!isRecord(value) || !Array.isArray(value['messages'])) throw invalidResponse();
  const sessionId = readString(value, 'session_id');
  if (sessionId === null) throw invalidResponse();
  return {
    session_id: sessionId,
    messages: value['messages'].map(parseMessage),
    terminal_turn_id: readNullableString(value, 'terminal_turn_id'),
    terminal_turn_kind: readNullableString(value, 'terminal_turn_kind'),
  };
}

function parseTurnResult(value: unknown): TurnResult {
  if (!isRecord(value)) throw invalidResponse();
  const turnId = readString(value, 'turn_id');
  if (turnId === null) throw invalidResponse();
  return { turn_id: turnId, message: parseMessage(value['message']) };
}

function readString(value: unknown, key: string): string | null {
  if (!isRecord(value)) return null;
  const field = value[key];
  return typeof field === 'string' ? field : null;
}

function readNullableString(value: Record<string, unknown>, key: string): string | null {
  const field = value[key];
  if (field === null) return null;
  if (typeof field === 'string') return field;
  throw invalidResponse();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidResponse(): RecipeChatNetworkError {
  return new RecipeChatNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
