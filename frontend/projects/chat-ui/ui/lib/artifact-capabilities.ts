import type { JsonValue } from './chat-message';

export interface ChatArtifactCapability {
  readonly type: string;
  readonly description: string;
  readonly payloadSchema: { readonly [key: string]: JsonValue };
}

export const JSON_ARTIFACT_CAPABILITY: ChatArtifactCapability = {
  type: 'json',
  description: 'Show structured JSON data when its structure is useful to the user. Prefer a purpose-specific presentation when available; use ordinary text for ordinary answers.',
  payloadSchema: {
    type: 'object',
    properties: { value: {} },
    required: ['value'],
    additionalProperties: false,
  },
};
