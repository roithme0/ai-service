import type {
  AppendMessageApiV1AgentsConfigurationSessionsSessionIdMessagesPostData,
  CompletedTurnResponse,
  CreateSessionApiV1AgentsConfigurationSessionsPostData,
  ErrorResponse,
  SessionCreationResponse,
  SessionSnapshotResponse,
  UserMessageResponse,
  ValidationErrorResponse,
} from '../generated/types.gen';
import {
  zCompletedTurnResponse,
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
  z.strictObject({ ...zValidationErrorResponse.shape, detail: z.array(validationDetailSchema).min(1) }),
]);

export const AgentConfiguration = zCreateSessionApiV1AgentsConfigurationSessionsPostPath.shape.configuration.enum;
export type AgentConfiguration = CreateSessionApiV1AgentsConfigurationSessionsPostData['path']['configuration'];

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
  generateTurn(sessionId: string): Promise<CompletedTurnResponse>;
}

export class HttpConversationTransport implements ConversationTransport {
  private readonly baseUrl: string;

  constructor(apiBaseUrl: string, configuration: AgentConfiguration, private readonly input: unknown = {}) {
    this.baseUrl = `${apiBaseUrl.replace(/\/+$/, '')}/agents/${encodeURIComponent(configuration)}/sessions`;
  }

  async createSession(): Promise<SessionCreationResponse> {
    const body = { input: this.input } satisfies CreateSessionApiV1AgentsConfigurationSessionsPostData['body'];
    return parseResponse(zSessionCreationResponse, await this.request('', 'POST', body));
  }

  async readSession(sessionId: string): Promise<SessionSnapshotResponse> {
    return parseResponse(zSessionSnapshotResponse, await this.request(`/${sessionId}`, 'GET'));
  }

  async appendMessage(sessionId: string, text: string): Promise<UserMessageResponse> {
    const body = { text } satisfies AppendMessageApiV1AgentsConfigurationSessionsSessionIdMessagesPostData['body'];
    return parseResponse(zUserMessageResponse, await this.request(`/${sessionId}/messages`, 'POST', body));
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
