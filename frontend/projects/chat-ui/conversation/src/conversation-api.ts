import type {
  ArtifactResponse,
  AssistantMessageResponse,
  CompletedTurnResponse,
  SessionCreationResponse,
  SessionSnapshotResponse,
  UserMessageResponse,
} from '../generated/types.gen';

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
    return parseSessionCreation(await this.request('', 'POST', { input: this.input }));
  }

  async readSession(sessionId: string): Promise<SessionSnapshotResponse> {
    return parseSessionSnapshot(await this.request(`/${sessionId}`, 'GET'));
  }

  async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    const message = parseMessage(await this.request(`/${sessionId}/messages`, 'POST', { text }));
    if (message.role !== 'user') throw invalidResponse();
    return message;
  }

  async generateTurn(sessionId: string): Promise<CompletedTurnResponse> {
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

function parseSessionCreation(value: unknown): SessionCreationResponse {
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
  const turnId = readNullableString(value, 'turn_id');
  if (role === 'user') {
    if (turnId !== null) throw invalidResponse();
    return { role, text, turn_id: null };
  }
  if (turnId === null) throw invalidResponse();
  return { role, text, turn_id: turnId };
}

function parseSessionSnapshot(value: unknown): SessionSnapshotResponse {
  if (!isRecord(value) || !Array.isArray(value['messages']) || !Array.isArray(value['artifacts'])) {
    throw invalidResponse();
  }
  const sessionId = readString(value, 'session_id');
  const expiresAt = readString(value, 'expires_at');
  if (sessionId === null || expiresAt === null) throw invalidResponse();
  const terminalTurnKind = readNullableString(value, 'terminal_turn_kind');
  if (!isTerminalTurnKind(terminalTurnKind)) throw invalidResponse();
  return {
    session_id: sessionId,
    expires_at: expiresAt,
    messages: value['messages'].map(parseMessage),
    artifacts: value['artifacts'].map(parseArtifact),
    terminal_turn_id: readNullableString(value, 'terminal_turn_id'),
    terminal_turn_kind: terminalTurnKind,
  };
}

function parseTurnResult(value: unknown): CompletedTurnResponse {
  if (!isRecord(value) || value['kind'] !== 'completed' || !Array.isArray(value['artifacts'])) throw invalidResponse();
  const turnId = readString(value, 'turn_id');
  if (turnId === null) throw invalidResponse();
  const message = parseMessage(value['message']);
  if (message.role !== 'assistant') throw invalidResponse();
  return {
    kind: 'completed',
    turn_id: turnId,
    message,
    artifacts: value['artifacts'].map(parseArtifact),
  };
}

function parseArtifact(value: unknown): ArtifactResponse {
  if (!isRecord(value)) throw invalidResponse();
  const artifactId = readString(value, 'artifact_id');
  const turnId = readString(value, 'turn_id');
  const type = readString(value, 'type');
  const createdAt = readString(value, 'created_at');
  if (artifactId === null || turnId === null || type === null || createdAt === null || !isRecord(value['payload'])) throw invalidResponse();
  return {
    artifact_id: artifactId,
    type,
    created_at: createdAt,
    order: readNumber(value, 'order'),
    turn_id: turnId,
    payload: value['payload'],
  };
}

function isTerminalTurnKind(value: string | null): value is SessionSnapshotResponse['terminal_turn_kind'] {
  return value === null || value === 'completed' || value === 'generation_failed' || value === 'unknown'
    || value === 'expired' || value === 'not_ready' || value === 'limit_reached' || value === 'conflict' || value === 'busy';
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalidResponse(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
