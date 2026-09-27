export const AgentConfiguration = { Demo: 'demo', Kochwiki: 'kochwiki' } as const;
export type AgentConfiguration = (typeof AgentConfiguration)[keyof typeof AgentConfiguration];

export interface ApiUserMessage {
  readonly role: 'user';
  readonly text: string;
  readonly turn_id: null;
}

export interface ApiAssistantMessage {
  readonly role: 'assistant';
  readonly text: string;
  readonly turn_id: string;
}

export type ApiMessage = ApiUserMessage | ApiAssistantMessage;

export interface SessionCreation {
  readonly session_id: string;
  readonly expires_at: string;
}

export interface SessionSnapshot {
  readonly session_id: string;
  readonly messages: ReadonlyArray<ApiMessage>;
  readonly artifacts: ReadonlyArray<ApiArtifact>;
  readonly terminal_turn_id: string | null;
  readonly terminal_turn_kind: string | null;
}

export interface TurnResult {
  readonly kind: 'completed';
  readonly turn_id: string;
  readonly message: ApiMessage;
  readonly artifacts: ReadonlyArray<ApiArtifact>;
}

export interface ApiArtifact {
  readonly artifact_id: string;
  readonly type: string;
  readonly created_at: string;
  readonly order: number;
  readonly turn_id: string;
  readonly payload: unknown;
}

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
  createSession(): Promise<SessionCreation>;
  readSession(sessionId: string): Promise<SessionSnapshot>;
  appendMessage(sessionId: string, text: string): Promise<ApiMessage>;
  generateTurn(sessionId: string): Promise<TurnResult>;
}

export class HttpConversationTransport implements ConversationTransport {
  private readonly baseUrl: string;

  constructor(apiBaseUrl: string, configuration: AgentConfiguration, private readonly input: unknown = {}) {
    this.baseUrl = `${apiBaseUrl.replace(/\/+$/, '')}/agents/${encodeURIComponent(configuration)}/sessions`;
  }

  async createSession(): Promise<SessionCreation> {
    return parseSessionCreation(await this.request('', 'POST', { input: this.input }));
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

function parseSessionCreation(value: unknown): SessionCreation {
  const sessionId = readString(value, 'session_id');
  const expiresAt = readString(value, 'expires_at');
  if (sessionId === null || expiresAt === null) throw invalidResponse();
  return { session_id: sessionId, expires_at: expiresAt };
}

function parseMessage(value: unknown): ApiMessage {
  if (!isRecord(value)) throw invalidResponse();
  const role = readString(value, 'role');
  const text = readString(value, 'text');
  if ((role !== 'user' && role !== 'assistant') || text === null) throw invalidResponse();
  const turnId = readOptionalNullableString(value, 'turn_id');
  if (role === 'user') {
    if (turnId !== null) throw invalidResponse();
    return { role, text, turn_id: null };
  }
  if (turnId === null) throw invalidResponse();
  return { role, text, turn_id: turnId };
}

function parseSessionSnapshot(value: unknown): SessionSnapshot {
  if (!isRecord(value) || !Array.isArray(value['messages']) || !Array.isArray(value['artifacts'])) {
    throw invalidResponse();
  }
  const sessionId = readString(value, 'session_id');
  if (sessionId === null) throw invalidResponse();
  return {
    session_id: sessionId,
    messages: value['messages'].map(parseMessage),
    artifacts: value['artifacts'].map(parseArtifact),
    terminal_turn_id: readNullableString(value, 'terminal_turn_id'),
    terminal_turn_kind: readNullableString(value, 'terminal_turn_kind'),
  };
}

function parseTurnResult(value: unknown): TurnResult {
  if (!isRecord(value) || value['kind'] !== 'completed' || !Array.isArray(value['artifacts'])) throw invalidResponse();
  const turnId = readString(value, 'turn_id');
  if (turnId === null) throw invalidResponse();
  return {
    kind: 'completed',
    turn_id: turnId,
    message: parseMessage(value['message']),
    artifacts: value['artifacts'].map(parseArtifact),
  };
}

function parseArtifact(value: unknown): ApiArtifact {
  if (!isRecord(value)) throw invalidResponse();
  const artifactId = readString(value, 'artifact_id');
  const turnId = readString(value, 'turn_id');
  const type = readString(value, 'type');
  const createdAt = readString(value, 'created_at');
  if (artifactId === null || turnId === null || type === null || createdAt === null || !('payload' in value)) throw invalidResponse();
  return {
    artifact_id: artifactId,
    type,
    created_at: createdAt,
    order: readNumber(value, 'order'),
    turn_id: turnId,
    payload: value['payload'],
  };
}

function readNumber(value: Record<string, unknown>, key: string): number {
  const field = value[key];
  if (typeof field !== 'number' || !Number.isFinite(field)) throw invalidResponse();
  return field;
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

function readOptionalNullableString(value: Record<string, unknown>, key: string): string | null {
  return value[key] === undefined ? null : readNullableString(value, key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidResponse(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
