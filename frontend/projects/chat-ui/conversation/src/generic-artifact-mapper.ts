import type { ChatArtifact, JsonValue } from '@roithme0/chat-ui/ui';
import { ConversationNetworkError, type ApiArtifact } from './conversation-api';

export function presentJsonArtifact(artifact: ApiArtifact): ChatArtifact {
  if (!isJsonValue(artifact.payload)) {
    throw new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
  }
  return {
    kind: 'artifact',
    id: artifact.artifact_id,
    type: artifact.type,
    headline: artifact.type,
    payload: artifact.payload,
  };
}

function isJsonValue(value: unknown, ancestors: ReadonlySet<object> = new Set<object>()): value is JsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value !== 'object' || ancestors.has(value)) return false;
  if (!Array.isArray(value) &&
    Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) return false;
  const nextAncestors = new Set(ancestors).add(value);
  const entries: readonly unknown[] = Array.isArray(value) ? value : Object.values(value);
  return entries.every((entry) => isJsonValue(entry, nextAncestors));
}
