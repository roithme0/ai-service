import { RECIPE_SESSION_FIXTURE } from './recipe-chat-fixture';

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

export interface FoodstuffSummary {
  readonly id: number;
  readonly name: string;
  readonly brand: string | null;
  readonly unit: 'G' | 'ML' | 'PIECE';
  readonly unitVerbose: string;
  readonly kcal: number | null;
  readonly carbs: number | null;
  readonly protein: number | null;
  readonly fat: number | null;
}

export interface RecipePresentation {
  readonly servings: number;
  readonly preptime: number | null;
  readonly kcal: number | null;
  readonly carbs: number | null;
  readonly protein: number | null;
  readonly fat: number | null;
  readonly ingredients: ReadonlyArray<{
    readonly index: number;
    readonly amount: number;
    readonly foodstuff: FoodstuffSummary;
  }>;
  readonly steps: ReadonlyArray<{ readonly index: number; readonly description: string }>;
}

export interface RecipeProposal {
  readonly artifact_id: string;
  readonly turn_id: string;
  readonly name: string;
  readonly recipe: RecipePresentation;
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
      readonly ingredients: ReadonlyArray<{
        readonly index: number;
        readonly amount: number;
        readonly foodstuff_reference: number;
      }>;
      readonly steps: ReadonlyArray<{ readonly index: number; readonly description: string }>;
    };
  };
  readonly foodstuffs: ReadonlyArray<{
    readonly external_reference: number;
    readonly name: string;
    readonly brand: string | null;
    readonly unit: 'G' | 'ML' | 'PIECE';
    readonly unit_verbose: string;
    readonly kcal: number | null;
    readonly carbs: number | null;
    readonly protein: number | null;
    readonly fat: number | null;
  }>;
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
  private readonly baseUrl = '/api/v1/agents/kochwiki/sessions';

  async createSession(): Promise<SessionCreation> {
    return parseSessionCreation(await this.request('', 'POST', { input: RECIPE_SESSION_FIXTURE }));
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

export function parseRecipeArtifact(artifact: ApiArtifact): RecipeProposal | null {
  if (artifact.type !== 'recipe.proposal') return null;
  if (!isRecord(artifact.payload)) throw invalidResponse();
  const name = readString(artifact.payload, 'name');
  if (name === null) throw invalidResponse();
  return {
    artifact_id: artifact.artifact_id,
    turn_id: artifact.turn_id,
    name,
    recipe: parsePresentation(artifact.payload['recipe']),
  };
}

function parsePresentation(value: unknown): RecipePresentation {
  if (!isRecord(value) || !Array.isArray(value['ingredients']) || !Array.isArray(value['steps'])) {
    throw invalidResponse();
  }
  return {
    servings: readNumber(value, 'servings'),
    preptime: readNullableNumber(value, 'preptime'),
    kcal: readNullableNumber(value, 'kcal'),
    carbs: readNullableNumber(value, 'carbs'),
    protein: readNullableNumber(value, 'protein'),
    fat: readNullableNumber(value, 'fat'),
    ingredients: value['ingredients'].map((ingredient) => {
      if (!isRecord(ingredient)) throw invalidResponse();
      return {
        index: readNumber(ingredient, 'index'),
        amount: readNumber(ingredient, 'amount'),
        foodstuff: parseFoodstuff(ingredient['foodstuff']),
      };
    }),
    steps: value['steps'].map((step) => {
      if (!isRecord(step)) throw invalidResponse();
      const description = readString(step, 'description');
      if (description === null) throw invalidResponse();
      return { index: readNumber(step, 'index'), description };
    }),
  };
}

function parseFoodstuff(value: unknown): FoodstuffSummary {
  if (!isRecord(value)) throw invalidResponse();
  const name = readString(value, 'name');
  const brand = readNullableString(value, 'brand');
  const unit = readString(value, 'unit');
  const unitVerbose = readString(value, 'unitVerbose');
  if (name === null || unitVerbose === null || (unit !== 'G' && unit !== 'ML' && unit !== 'PIECE')) {
    throw invalidResponse();
  }
  return {
    id: readNumber(value, 'id'), name, brand, unit, unitVerbose,
    kcal: readNullableNumber(value, 'kcal'), carbs: readNullableNumber(value, 'carbs'),
    protein: readNullableNumber(value, 'protein'), fat: readNullableNumber(value, 'fat'),
  };
}

function readNumber(value: Record<string, unknown>, key: string): number {
  const field = value[key];
  if (typeof field !== 'number' || !Number.isFinite(field)) throw invalidResponse();
  return field;
}

function readNullableNumber(value: Record<string, unknown>, key: string): number | null {
  return value[key] === null ? null : readNumber(value, key);
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

function invalidResponse(): RecipeChatNetworkError {
  return new RecipeChatNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
}
