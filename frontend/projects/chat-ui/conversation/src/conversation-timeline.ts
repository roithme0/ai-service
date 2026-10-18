import type { SessionSnapshotResponse } from '../generated/types.gen';
import { ConversationNetworkError } from './conversation-api';

export function validateSnapshot(snapshot: SessionSnapshotResponse, sessionId: string): void {
  if (snapshot.session_id !== sessionId) throw invalidTimeline();
  const turns = new Set<string>();
  const identities = new Set<string>();
  for (const turn of snapshot.turns) {
    if (turns.has(turn.turn_id)) throw invalidTimeline();
    turns.add(turn.turn_id);
    const anchor = turn.timeline[0];
    if (anchor?.kind !== 'message' || anchor.role !== 'user' || anchor.id !== turn.user_message_id)
      throw invalidTimeline();
    for (const item of turn.timeline) {
      const identity = itemIdentity(item);
      if (
        item.turn_id !== turn.turn_id ||
        identities.has(identity) ||
        (item.kind === 'artifact' && item.artifact.turn_id !== turn.turn_id)
      )
        throw invalidTimeline();
      identities.add(identity);
    }
  }
}

export function itemIdentity(
  item: SessionSnapshotResponse['turns'][number]['timeline'][number],
): string {
  switch (item.kind) {
    case 'message':
    case 'intermediate':
      return item.id;
    case 'tool':
      return `tool-${item.execution_id}`;
    case 'artifact':
      return item.artifact.artifact_id;
    case 'failure':
      return `failure-${item.turn_id}`;
  }
}

function invalidTimeline(): ConversationNetworkError {
  return new ConversationNetworkError('Der Backend-Dienst hat eine ungültige Timeline gesendet.');
}
