import type { JsonValue } from './chat-message';

export interface ChatArtifactCapability {
  readonly type: string;
  readonly description: string;
  readonly titleDescription?: string;
  readonly subtitleDescription?: string;
  readonly payloadSchema: { readonly [key: string]: JsonValue };
  readonly metadataSchema?: { readonly [key: string]: JsonValue };
}

export const JSON_ARTIFACT_CAPABILITY: ChatArtifactCapability = {
  type: 'json',
  description: 'Display structured JSON data for inspection.',
  titleDescription: 'Use a short, user-facing label describing the presented data.',
  subtitleDescription: 'Omit unless a short secondary label helps explain the presented data.',
  payloadSchema: {
    type: 'object',
    properties: { value: {} },
    required: ['value'],
    additionalProperties: false,
  },
};
