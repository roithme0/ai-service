import type { ChatArtifact, JsonValue } from '@roithme0/chat-ui/ui';
import { ConversationNetworkError } from './conversation-api';
import type { ArtifactResponse } from '../generated/types.gen';

export function presentJsonArtifact(artifact: ArtifactResponse): ChatArtifact {
  if (!isJsonValue(artifact.payload)) {
    throw new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Antwort gesendet.');
  }
  return {
    kind: 'artifact',
    id: artifact.artifact_id,
    type: 'json',
    headline: artifact.type,
    payload: { value: artifact.payload },
  };
}

export function presentArtifact(artifact: ArtifactResponse): ChatArtifact {
  const envelope = artifact.payload;
  if (!isJsonValue(envelope) || envelope === null || Array.isArray(envelope)
    || typeof envelope !== 'object' || typeof envelope['title'] !== 'string'
    || !envelope['title'].trim() || !('payload' in envelope)
    || (envelope['subtitle'] != null && (typeof envelope['subtitle'] !== 'string' || !envelope['subtitle'].trim()))) {
    throw new ConversationNetworkError('Der Backend-Dienst hat eine ung\u00fcltige Darstellung gesendet.');
  }
  return {
    kind: 'artifact', id: artifact.artifact_id, type: artifact.type,
    headline: envelope['title'], payload: envelope['payload'],
    ...(typeof envelope['subtitle'] === 'string' ? { subtitle: envelope['subtitle'] } : {}),
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
