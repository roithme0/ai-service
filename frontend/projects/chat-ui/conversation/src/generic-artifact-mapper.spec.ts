import { describe, expect, it } from 'vitest';
import { ConversationNetworkError } from './conversation-api';
import type { ArtifactResponse } from '../generated/types.gen';
import { presentArtifact, presentJsonArtifact } from './generic-artifact-mapper';

const artifact: ArtifactResponse = {
  artifact_id: 'artifact-1', type: 'other.result', created_at: '2026-09-25T12:00:00Z',
  order: 1, turn_id: 'turn-1', payload: { nested: [null, true, 2] },
};

describe('generic artifact mapping', () => {
  it('passes metadata to the host separately from the renderer payload', () => {
    const mapped = presentArtifact({ ...artifact, payload: {
      title: 'Data', payload: { value: 42 }, metadata: { reference: 'stored-object' },
    } });
    expect(mapped.metadata).toEqual({ reference: 'stored-object' });
    expect(mapped.payload).toEqual({ value: 42 });
    for (const metadata of [42, 'id', []]) {
      expect(() => presentArtifact({ ...artifact, payload: { title: 'Data', payload: {}, metadata } }))
        .toThrow(ConversationNetworkError);
    }
  });
  it('explicitly selects JSON presentation for arbitrary backend data', () => {
    expect(presentJsonArtifact(artifact)).toEqual({
      kind: 'artifact', id: 'artifact-1', type: 'json', headline: 'other.result',
      payload: { value: { nested: [null, true, 2] } },
    });
  });

  it('maps a presentation without choosing a different renderer', () => {
    expect(presentArtifact({ ...artifact, type: 'json', payload: {
      title: 'Selected ingredient', payload: { value: { name: 'Oats' } },
    } })).toEqual({ kind: 'artifact', id: 'artifact-1', type: 'json',
      headline: 'Selected ingredient', payload: { value: { name: 'Oats' } } });
    expect(() => presentArtifact(artifact)).toThrow(ConversationNetworkError);
  });

  it('rejects values outside the library JSON contract', () => {
    const cycle: Record<string, unknown> = {};
    cycle['self'] = cycle;
    for (const payload of [undefined, new Date(), { missing: undefined }, cycle]) {
      expect(() => presentJsonArtifact({ ...artifact, payload } as ArtifactResponse)).toThrow(ConversationNetworkError);
    }
  });

  it('maps an optional subtitle and accepts its absence or null', () => {
    const presentation = { ...artifact, payload: { title: 'Oats', subtitle: 'Example brand', payload: {} } };
    expect(presentArtifact(presentation).subtitle).toBe('Example brand');
    expect(presentArtifact({ ...presentation, payload: { title: 'Oats', payload: {} } }).subtitle).toBeUndefined();
    expect(presentArtifact({ ...presentation, payload: { title: 'Oats', subtitle: null, payload: {} } }).subtitle).toBeUndefined();
  });

  it('rejects malformed and blank subtitles', () => {
    for (const subtitle of [12, {}, '', '   ']) {
      expect(() => presentArtifact({ ...artifact, payload: { title: 'Oats', subtitle, payload: {} } }))
        .toThrow(ConversationNetworkError);
    }
  });
});
