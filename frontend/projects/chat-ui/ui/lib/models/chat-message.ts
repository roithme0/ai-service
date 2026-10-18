import type { TemplateRef } from '@angular/core';

export type ChatMessageRole = 'user' | 'assistant';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue =
  JsonPrimitive | readonly JsonValue[] | { readonly [key: string]: JsonValue };

export type ChatTurnStatus = 'active' | 'completed' | 'failed' | 'unknown';

export interface ChatTurn {
  readonly id: string;
  readonly userMessageId: string;
  readonly status: ChatTurnStatus;
  readonly content: readonly ChatContent[];
}

export interface ChatTurnContent {
  readonly turnId?: string;
}

export interface ChatTextMessage extends ChatTurnContent {
  readonly kind: 'text';
  readonly id: string;
  readonly role: ChatMessageRole;
  readonly text: string;
}

export interface ChatArtifact<TPayload extends JsonValue = JsonValue> extends ChatTurnContent {
  readonly kind: 'artifact';
  readonly id: string;
  readonly type: string;
  readonly headline: string;
  readonly subtitle?: string;
  readonly payload: TPayload;
  readonly metadata?: { readonly [key: string]: JsonValue };
}

export type ChatToolStatus =
  'requested' | 'running' | 'completed' | 'failed' | 'not_executed' | 'outcome_unknown';

export interface ChatToolCall extends ChatTurnContent {
  readonly kind: 'tool';
  readonly id: string;
  readonly name: string;
  readonly status: ChatToolStatus;
}

export interface ChatIntermediateMessage extends ChatTurnContent {
  readonly kind: 'intermediate';
  readonly id: string;
  readonly text: string;
}

export interface ChatTurnFailure extends ChatTurnContent {
  readonly kind: 'failure';
  readonly id: string;
  readonly text: string;
}

export type ChatContent =
  ChatTextMessage | ChatIntermediateMessage | ChatArtifact | ChatToolCall | ChatTurnFailure;

export interface ChatArtifactRenderContext<TPayload extends JsonValue> {
  readonly $implicit: TPayload;
  readonly artifact: ChatArtifact<TPayload>;
}

export interface ChatArtifactRenderer<TPayload extends JsonValue = JsonValue> {
  readonly template: TemplateRef<ChatArtifactRenderContext<TPayload>>;
}

export type ChatArtifactRendererMap = Readonly<Record<string, ChatArtifactRenderer>>;

export function artifactRenderer<TPayload extends JsonValue>(
  template: TemplateRef<ChatArtifactRenderContext<TPayload>>,
): ChatArtifactRenderer<TPayload> {
  return { template };
}

export interface ChatSubmission {
  readonly text: string;
  readonly acknowledge: () => void;
}

export interface ChatStatusAction {
  readonly id: string;
  readonly label: string;
}

export interface ChatConversationStatus {
  readonly kind: 'loading' | 'error';
  readonly message: string;
  readonly placement: 'conversation' | 'assistant';
  readonly reveal?: 'delayed';
  readonly action?: ChatStatusAction;
}
