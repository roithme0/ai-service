import { describe, expect, it } from 'vitest';
import type { PresentedSession, PresentedTurn, PresentationPart } from '../generated/types.gen';
import { presentSession } from './session-presentation';

const EMPTY_USAGE: PresentedSession['usage'] = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  requests: 0,
  tool_calls: 0,
  estimated_cost_usd: null,
};

const time = '2026-10-21T12:00:00Z';
function run(
  status: PresentedTurn['lifecycle']['status'] = 'running',
  parts: PresentationPart[] = [],
  runId: string | null = 'run',
): PresentedTurn {
  return {
    part_kind: 'turn',
    usage: EMPTY_USAGE,
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
  return { session_id: 'session', expires_at: time, history, error: null, usage: EMPTY_USAGE };
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
    run_id: 'run',
    created_at: time,
    content: { title: 'Result', payload: { value: 'A'.repeat(1000) } },
  },
};
const answer: PresentationPart = { part_kind: 'text', phase: 'final_answer', content: 'Answer' };
const unphased: PresentationPart = { part_kind: 'text', content: 'Unphased', phase: null };
const commentary: PresentationPart = {
  part_kind: 'text',
  content: 'Commentary',
  phase: 'commentary',
};

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

  it('preserves explicit final markers across separated groups without promoting unphased text', () => {
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
    expect(
      presentSession(snapshot([run('completed', [tool, commentary])]))[0].content.every(
        (item) => item.kind !== 'text',
      ),
    ).toBe(true);
  });

  it.each([
    { status: 'running', observationLost: false },
    { status: 'running', observationLost: true },
    { status: 'completed', observationLost: false },
    { status: 'failed', observationLost: false },
    { status: 'cancelled', observationLost: false },
  ] as const)(
    'never infers a final answer from unphased text ($status, observationLost=$observationLost)',
    ({ status, observationLost }) => {
      const result = presentSession(
        snapshot([
          run(status, [tool, unphased]),
          { part_kind: 'user-prompt', content: 'Independent prompt' },
          run(status, [{ ...unphased, content: 'Last' }, commentary]),
        ]),
        observationLost,
      );
      const messages = result
        .flatMap((group) => group.content)
        .filter((item) => item.kind === 'text');
      expect(messages.map((item) => ({ text: item.text, isFinal: item.isFinal }))).toEqual([
        { text: 'Unphased', isFinal: false },
        { text: 'Independent prompt', isFinal: false },
        { text: 'Last', isFinal: false },
      ]);
      expect(result[2].content[1]).toMatchObject({ kind: 'intermediate', text: 'Commentary' });
    },
  );

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
