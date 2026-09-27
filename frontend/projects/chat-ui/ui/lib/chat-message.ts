import type { TemplateRef } from '@angular/core';

export type ChatMessageRole = 'user' | 'assistant';

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | readonly JsonValue[] | { readonly [key: string]: JsonValue };

export interface ChatTextMessage {
  readonly kind: 'text';
  readonly id: string;
  readonly role: ChatMessageRole;
  readonly text: string;
}

export interface ChatArtifact<TPayload extends JsonValue = JsonValue> {
  readonly kind: 'artifact';
  readonly id: string;
  readonly type: string;
  readonly headline: string;
  readonly payload: TPayload;
}

export type ChatContent = ChatTextMessage | ChatArtifact;

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
  readonly action?: ChatStatusAction;
}
