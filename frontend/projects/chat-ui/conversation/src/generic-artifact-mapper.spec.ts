import { describe, expect, it } from 'vitest';
import { ConversationNetworkError, type ApiArtifact } from './conversation-api';
import { presentJsonArtifact } from './generic-artifact-mapper';

const artifact: ApiArtifact = {
  artifact_id: 'artifact-1', type: 'other.result', created_at: '2026-09-25T12:00:00Z',
  order: 1, turn_id: 'turn-1', payload: { nested: [null, true, 2] },
};

describe('generic artifact mapping', () => {
  it('preserves backend identity, type, and JSON payload', () => {
    expect(presentJsonArtifact(artifact)).toEqual({
      kind: 'artifact', id: 'artifact-1', type: 'other.result', headline: 'other.result',
      payload: { nested: [null, true, 2] },
    });
  });

  it('rejects values outside the library JSON contract', () => {
    const cycle: Record<string, unknown> = {};
    cycle['self'] = cycle;
    for (const payload of [undefined, new Date(), { missing: undefined }, cycle]) {
      expect(() => presentJsonArtifact({ ...artifact, payload })).toThrow(ConversationNetworkError);
    }
  });
});
