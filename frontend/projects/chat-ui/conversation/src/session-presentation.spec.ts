import { describe, expect, it } from 'vitest';
import type { PresentedSession, PresentedTurn, PresentationPart } from '../generated/types.gen';
import { presentSession } from './session-presentation';

const time = '2026-10-21T12:00:00Z';
function run(
  status: PresentedTurn['lifecycle']['status'] = 'running',
  parts: PresentationPart[] = [],
  runId: string | null = 'run',
): PresentedTurn {
  return {
    part_kind: 'turn',
    lifecycle: {
      run_id: runId,
      status,
      started_at: time,
      finished_at: status === 'running' ? null : time,
    },
    parts,
  };
}
function snapshot(history: PresentedSession['history'] = []): PresentedSession {
  return { session_id: 'session', expires_at: time, history };
}
const tool: PresentationPart = {
  part_kind: 'tool-call',
  tool_call_id: 'call',
  tool_name: 'publish',
  status: 'running',
};
const artifact: PresentationPart = {
  part_kind: 'artifact',
  artifact: {
    artifact_id: 'artifact',
    type: 'json',
    turn_id: 'run',
    created_at: time,
    order: 0,
    payload: { title: 'Result', payload: { value: 'A'.repeat(1000) } },
  },
};
const answer: PresentationPart = { part_kind: 'text', phase: 'final_answer', content: 'Answer' };

describe('native session presentation', () => {
  it('preserves independent repeated prompt fragments and ordered tool/artifact groups', () => {
    const result = presentSession(
      snapshot([
        { part_kind: 'user-prompt', content: ['same', 'same'] },
        run('running', [tool, artifact]),
        { part_kind: 'user-prompt', content: 'same' },
        run('running', [answer]),
        run('failed', [], null),
        run('failed', [], null),
      ]),
    );
    expect(result.map((group) => group.content.map((item) => item.kind))).toEqual([
      ['text', 'text'],
      ['tool', 'artifact'],
      ['text'],
      ['text'],
      ['failure'],
      ['failure'],
    ]);
    expect(result[1].runKey).toBe(result[3].runKey);
    expect(result[4].runKey).not.toBe(result[5].runKey);
    const otherSession = presentSession({
      ...snapshot([run('completed', [answer])]),
      session_id: 'other',
    });
    expect(otherSession[0].runKey).not.toBe(result[1].runKey);
    expect(result[0].content.map((item) => item.id)).toEqual([
      '"session":prompt-0-0',
      '"session":prompt-0-1',
    ]);
  });

  it('preserves run keys when a null run ID is captured and when an empty lifecycle precedes another run', () => {
    const before = presentSession(
      snapshot([run('failed', [], null), run('running', [tool, artifact], null)]),
    );
    const after = presentSession(
      snapshot([run('failed', [], null), run('completed', [tool, artifact, answer], 'captured')]),
    );
    expect(after.map((group) => group.runKey)).toEqual(before.map((group) => group.runKey));
    expect(after[1].content[1]).toEqual(before[1].content[1]);
  });

  it('chooses explicit final text across separated groups, otherwise the last unphased text, never commentary', () => {
    const unphased: PresentationPart = { part_kind: 'text', content: 'Unphased', phase: null };
    const commentary: PresentationPart = {
      part_kind: 'text',
      content: 'Commentary',
      phase: 'commentary',
    };
    const explicit = presentSession(
      snapshot([
        run('completed', [tool, answer, { ...answer, content: 'Another final' }]),
        { part_kind: 'user-prompt', content: 'next' },
        run('completed', [unphased, commentary]),
      ]),
    );
    expect(explicit[0].content[1]).toMatchObject({ kind: 'text', isFinal: true });
    expect(explicit[0].content[2]).toMatchObject({
      kind: 'text',
      isFinal: true,
      text: 'Another final',
    });
    expect(explicit[2].content[0]).toMatchObject({ kind: 'text', isFinal: false });
    expect(explicit[2].content.map((item) => item.kind)).toEqual(['text', 'intermediate']);
    const fallback = presentSession(
      snapshot([run('completed', [tool, unphased, { ...unphased, content: 'Last' }, commentary])]),
    );
    expect(fallback[0].content.map((item) => item.kind)).toEqual([
      'tool',
      'text',
      'text',
      'intermediate',
    ]);
    expect(fallback[0].content[2]).toMatchObject({ isFinal: true, text: 'Last' });
    expect(
      presentSession(snapshot([run('completed', [tool, commentary])]))[0].content.every(
        (item) => item.kind !== 'text',
      ),
    ).toBe(true);
  });

  it('retains terminal lifecycles after observation loss and supports omitted artifacts', () => {
    const result = presentSession(
      snapshot([
        run('completed', [answer]),
        run('failed', [], 'failed'),
        run('cancelled', [], 'cancelled'),
        run('running', [artifact], 'active'),
      ]),
      true,
      () => null,
    );
    expect(result.map((group) => group.status)).toEqual([
      'completed',
      'failed',
      'cancelled',
      'unknown',
    ]);
    expect(result[3].content).toEqual([]);
  });

  it.each(['failed', 'cancelled'] as const)(
    'shows one %s marker at the end of a split run',
    (status) => {
      const result = presentSession(
        snapshot([
          run(status, [tool]),
          { part_kind: 'user-prompt', content: 'Independent prompt' },
          run(status, [answer]),
        ]),
      );

      expect(result[0].runKey).toBe(result[2].runKey);
      expect(result[1].runKey).toBeNull();
      expect(result.map((section) => section.content.map((part) => part.kind))).toEqual([
        ['tool'],
        ['text'],
        ['text', 'failure'],
      ]);
    },
  );
});
