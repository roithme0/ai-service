import { describe, expect, it, vi } from 'vitest';
import type { ChatContent } from '@roithme0/chat-ui/ui';
import { type ConversationViewState, ConversationController } from './conversation-controller';
import {
  ConversationApiError,
  ConversationNetworkError,
  type ConversationTransport,
} from './conversation-api';
import type {
  AcceptedTurnResponse,
  SessionCreationResponse,
  SessionSnapshotResponse,
  StreamEvent,
  UserMessageResponse,
} from '../generated/types.gen';

class FakeTransport implements ConversationTransport {
  createSession = vi
    .fn<() => Promise<SessionCreationResponse>>()
    .mockResolvedValue({ session_id: 's', expires_at: '2026-10-04T20:00:00Z' });
  readSession = vi.fn<(id: string) => Promise<SessionSnapshotResponse>>();
  appendMessage = vi
    .fn<(id: string, text: string) => Promise<UserMessageResponse>>()
    .mockResolvedValue({ role: 'user', text: 'Hello', turn_id: 't' });
  generateTurn = vi
    .fn<(id: string) => Promise<AcceptedTurnResponse>>()
    .mockResolvedValue({ kind: 'accepted', turn_id: 't' });
  observeTurn =
    vi.fn<(id: string, turn: string, signal: AbortSignal) => AsyncIterable<StreamEvent>>();
}
function snapshot(overrides: Partial<SessionSnapshotResponse> = {}): SessionSnapshotResponse {
  return {
    session_id: 's',
    expires_at: '2026-10-04T20:00:00Z',
    sequence: 1,
    turns: [
      {
        turn_id: 't',
        user_message_id: 'confirmed-0-user',
        status: 'in_progress',
        timeline: [
          { kind: 'message', role: 'user', id: 'confirmed-0-user', text: 'Hello', turn_id: 't' },
        ],
      },
    ],
    ...overrides,
  };
}
const initial = (): StreamEvent => ({ kind: 'snapshot', turn_id: 't', snapshot: snapshot() });
const terminal = (
  outcome: 'completed' | 'generation_failed' | 'conflict' = 'completed',
): StreamEvent => ({
  kind: 'terminal',
  turn_id: 't',
  sequence: 10,
  outcome,
});
const tool = (
  status: 'requested' | 'running' | 'completed',
  sequence: number,
): Extract<StreamEvent, { kind: 'upsert' }> => ({
  kind: 'upsert',
  turn_id: 't',
  sequence,
  identity: 'tool-e',
  order: 2,

  item: { kind: 'tool', turn_id: 't', execution_id: 'e', name: 'save', status },
});
async function* stream(events: readonly StreamEvent[]): AsyncIterable<StreamEvent> {
  for (const event of events) yield await Promise.resolve(event);
}
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('live conversation controller', () => {
  it.each(['completed', 'failed', 'unknown'] as const)(
    'retains authoritative historical outcomes and current %s across interleaved output',
    async (ending) => {
      const transport = new FakeTransport();
      const timeline: SessionSnapshotResponse['turns'][number]['timeline'] = [
        { kind: 'message', role: 'user', id: 'request-first', text: 'First', turn_id: 'old' },
        { kind: 'message', role: 'assistant', id: 'old-answer', text: 'Done', turn_id: 'old' },
        {
          kind: 'message',
          role: 'user',
          id: 'request-second',
          text: 'Second',
          turn_id: 'failed',
        },
        { kind: 'intermediate', id: 'old-detail', text: 'Received', turn_id: 'failed' },
        { kind: 'failure', turn_id: 'failed' },
        { kind: 'message', role: 'user', id: 'request-current', text: 'Third', turn_id: 't' },
        { kind: 'intermediate', id: 'detail-before', text: 'Before', turn_id: 't' },
        {
          kind: 'artifact',
          turn_id: 't',
          artifact: {
            artifact_id: 'a',
            turn_id: 't',
            type: 'json',
            order: 1,
            created_at: '2026-10-18T10:00:00Z',
            payload: { title: 'Data', payload: 1 },
          },
        },
        { kind: 'intermediate', id: 'detail-after', text: 'After', turn_id: 't' },
        { kind: 'message', role: 'assistant', id: 'answer', text: 'Final', turn_id: 't' },
      ];
      transport.observeTurn.mockImplementation(async function* () {
        yield await Promise.resolve<StreamEvent>({
          kind: 'snapshot',
          turn_id: 't',
          snapshot: snapshot({
            turns: [
              {
                turn_id: 'old',
                user_message_id: 'request-first',
                status: 'completed',
                timeline: timeline.slice(0, 2),
              },
              {
                turn_id: 'failed',
                user_message_id: 'request-second',
                status: 'generation_failed',
                timeline: timeline.slice(2, 5),
              },
              {
                turn_id: 't',
                user_message_id: 'request-current',
                status: 'closing',
                timeline: timeline.slice(5),
              },
            ],
          }),
        });
        expect(controller.state.turns).toMatchObject([
          { id: 'old', userMessageId: 'request-first', status: 'completed' },
          { id: 'failed', userMessageId: 'request-second', status: 'failed' },
          { id: 't', userMessageId: 'request-current', status: 'active' },
        ]);
        expect(controller.state.turns.map((turn) => turn.content.map((item) => item.id))).toEqual([
          ['request-first', 'old-answer'],
          ['request-second', 'old-detail', 'failure-failed'],
          ['request-current', 'detail-before', 'a', 'detail-after', 'answer'],
        ]);
        expect(controller.state.composerDisabled).toBe(true);
        expect(contentOf(controller.state).map((item) => item.turnId)).toEqual(
          timeline.map((item) => item.turn_id),
        );
        expect(contentOf(controller.state).map((item) => item.kind)).toEqual([
          'text',
          'text',
          'text',
          'intermediate',
          'failure',
          'text',
          'intermediate',
          'artifact',
          'intermediate',
          'text',
        ]);
        if (ending !== 'unknown')
          yield terminal(ending === 'completed' ? 'completed' : 'generation_failed');
      });
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Third', vi.fn());
      expect(controller.state.turns.map((turn) => turn.status)).toEqual([
        'completed',
        'failed',
        ending,
      ]);
      expect(contentOf(controller.state).map((item) => item.id)).toContain('detail-after');
      expect(contentOf(controller.state).map((item) => item.id)).toContain('answer');
    },
  );

  it('shows no sending indicator and starts dots only with the accepted user message in history', async () => {
    const transport = new FakeTransport();
    const accepted = deferred<UserMessageResponse>();
    transport.appendMessage.mockReturnValue(accepted.promise);
    transport.observeTurn.mockReturnValue(stream([initial(), terminal()]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn(() => {
      expect(controller.state.turns).toHaveLength(1);
      expect(controller.state.turns[0]).toMatchObject({ id: 't', status: 'active' });
      expect(contentOf(controller.state)).toContainEqual(
        expect.objectContaining({ role: 'user', text: 'Hello', turnId: 't' }),
      );
      expect(controller.state.status).toMatchObject({ kind: 'loading', placement: 'assistant' });
      expect(controller.state.status).not.toHaveProperty('reveal');
    });
    const submission = controller.submit('Hello', acknowledge);
    expect(controller.state.status).toBeNull();
    expect(contentOf(controller.state)).toEqual([]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.generateTurn).not.toHaveBeenCalled();
    accepted.resolve({ role: 'user', text: 'Hello', turn_id: 't' });
    await submission;
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(controller.state.status).toBeNull();
    expect(controller.state.composerDisabled).toBe(false);
  });

  it.each(['intermediate', 'tool', 'artifact', 'message'] as const)(
    'hides loading on the first visible %s, ignoring previous-turn content',
    async (kind) => {
      const transport = new FakeTransport();
      const controller = new ConversationController(transport, () => undefined);
      transport.observeTurn.mockImplementation(async function* () {
        yield await Promise.resolve<StreamEvent>({
          kind: 'snapshot',
          turn_id: 't',
          snapshot: snapshot({
            turns: [
              {
                turn_id: 'old',
                user_message_id: 'old-user',
                status: 'completed',
                timeline: [
                  {
                    kind: 'message',
                    role: 'user',
                    id: 'old-user',
                    text: 'Previous',
                    turn_id: 'old',
                  },
                  { kind: 'intermediate', id: 'old', text: 'Previous turn', turn_id: 'old' },
                ],
              },
              ...snapshot().turns,
            ],
          }),
        });
        expect(controller.state.status?.kind).toBe('loading');
        const item: SessionSnapshotResponse['turns'][number]['timeline'][number] =
          kind === 'intermediate'
            ? { kind, turn_id: 't', id: 'first', text: 'Checking' }
            : kind === 'tool'
              ? { kind, turn_id: 't', execution_id: 'first', name: 'check', status: 'requested' }
              : kind === 'artifact'
                ? {
                    kind,
                    turn_id: 't',
                    artifact: {
                      artifact_id: 'first',
                      turn_id: 't',
                      type: 'json',
                      order: 2,
                      created_at: '2026-10-18T10:00:00Z',
                      payload: { title: 'Data', payload: 1 },
                    },
                  }
                : { kind, turn_id: 't', id: 'first', role: 'assistant', text: 'Done' };
        yield {
          kind: 'upsert',
          turn_id: 't',
          sequence: 2,
          order: 1,
          identity: kind === 'tool' ? 'tool-first' : 'first',
          item,
        };
        expect(controller.state.status).toBeNull();
        expect(controller.state.composerDisabled).toBe(true);
        yield { ...tool('running', 3), order: 2 };
        expect(controller.state.status).toBeNull();
        yield terminal();
      });
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(transport.observeTurn).toHaveBeenCalledOnce();
      expect(controller.state.composerDisabled).toBe(false);
    },
  );

  it.each(['event', 'snapshot'] as const)(
    'hides progress on backend closing %s and keeps submission disabled until terminal failure',
    async (source) => {
      const transport = new FakeTransport();
      const visible = deferred<void>();
      const finish = deferred<void>();
      transport.observeTurn.mockImplementation(async function* () {
        yield {
          kind: 'snapshot',
          turn_id: 't',
          snapshot: snapshot({
            turns: [
              {
                turn_id: 't',
                user_message_id: 'confirmed-0-user',
                status: source === 'snapshot' ? 'closing' : 'in_progress',
                timeline: [
                  {
                    kind: 'message',
                    role: 'user',
                    id: 'confirmed-0-user',
                    text: 'Hello',
                    turn_id: 't',
                  },
                  {
                    kind: 'message',
                    turn_id: 't',
                    id: 'answer',
                    role: 'assistant',
                    text: 'Retained answer',
                  },
                ],
              },
            ],
          }),
        };
        if (source === 'event') yield { kind: 'closing', turn_id: 't', sequence: 2 };
        yield tool('running', 3);
        visible.resolve();
        await finish.promise;
        yield terminal('generation_failed');
      });
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      const submission = controller.submit('Hello', vi.fn());
      await visible.promise;
      expect(controller.state.status).toBeNull();
      expect(controller.state.composerDisabled).toBe(true);
      await controller.submit('Blocked', vi.fn());
      expect(transport.appendMessage).toHaveBeenCalledTimes(1);
      finish.resolve();
      await submission;
      expect(controller.state.status?.kind).toBe('error');
      expect(controller.state.composerDisabled).toBe(false);
      expect(contentOf(controller.state)[1]).toMatchObject({ text: 'Retained answer' });
    },
  );

  it('hides dots for snapshot output and starts waiting again on the next turn', async () => {
    const transport = new FakeTransport();
    transport.generateTurn.mockResolvedValueOnce({ kind: 'accepted', turn_id: 'first' });
    transport.generateTurn.mockResolvedValueOnce({ kind: 'accepted', turn_id: 'second' });
    const statuses: (string | null)[] = [];
    const controller = new ConversationController(transport, () => undefined);
    transport.observeTurn.mockImplementation(async function* (_id, turnId) {
      statuses.push(controller.state.status?.kind ?? null);
      yield await Promise.resolve<StreamEvent>({
        kind: 'snapshot',
        turn_id: turnId,
        snapshot: snapshot({
          turns: [
            {
              turn_id: turnId,
              user_message_id: 'confirmed-0-user',
              status: 'in_progress',
              timeline: [
                {
                  kind: 'message',
                  role: 'user',
                  id: 'confirmed-0-user',
                  text: 'Hello',
                  turn_id: turnId,
                },
                { kind: 'intermediate', id: turnId, turn_id: turnId, text: 'Already working' },
              ],
            },
          ],
        }),
      });
      statuses.push(controller.state.status?.kind ?? null);
      yield { ...terminal(), turn_id: turnId };
    });
    await controller.start();
    await controller.submit('One', vi.fn());
    await controller.submit('Two', vi.fn());
    expect(statuses).toEqual(['loading', null, 'loading', null]);
  });

  it('keeps loading hidden when start recovery already reveals turn output', async () => {
    const transport = new FakeTransport();
    transport.generateTurn.mockRejectedValue(new ConversationNetworkError('offline'));
    transport.readSession.mockResolvedValue(
      snapshot({
        turns: [
          {
            ...snapshot().turns[0],
            timeline: [
              ...snapshot().turns[0].timeline,
              { kind: 'intermediate', id: 'working', turn_id: 't', text: 'Working' },
            ],
          },
        ],
      }),
    );
    const statuses: (string | null)[] = [];
    const controller = new ConversationController(transport, () => undefined);
    transport.observeTurn.mockImplementation(async function* () {
      statuses.push(controller.state.status?.kind ?? null);
      yield await Promise.resolve(initial());
      statuses.push(controller.state.status?.kind ?? null);
      yield terminal();
    });
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(statuses).toEqual([null, null]);
  });

  it('shows complete messages while busy, preserves all styles/output on failure, and upserts without regression', async () => {
    const transport = new FakeTransport();
    const visible = deferred<void>();
    const finish = deferred<void>();
    transport.observeTurn.mockImplementation(async function* () {
      yield initial();
      yield {
        kind: 'upsert',
        turn_id: 't',
        sequence: 2,
        identity: 'commentary',
        order: 1,

        item: { kind: 'intermediate', turn_id: 't', id: 'commentary', text: 'Checking' },
      };
      yield tool('requested', 3);
      yield tool('running', 4);
      yield tool('requested', 3);
      yield tool('completed', 5);
      yield {
        kind: 'upsert',
        turn_id: 't',
        sequence: 6,
        identity: 'final',
        order: 3,

        item: {
          kind: 'message',
          turn_id: 't',
          id: 'final',
          role: 'assistant',
          text: 'Looks complete',
        },
      };
      yield {
        kind: 'upsert',
        turn_id: 't',
        sequence: 7,
        identity: 'a',
        order: 4,
        item: {
          kind: 'artifact',
          turn_id: 't',
          artifact: {
            artifact_id: 'a',
            type: 'json',
            created_at: '2026-10-04T18:00:00Z',
            turn_id: 't',
            order: 4,
            payload: { title: 'Data', payload: { value: 1 } },
          },
        },
      };
      visible.resolve();
      await finish.promise;
      yield {
        kind: 'upsert',
        turn_id: 't',
        sequence: 8,
        identity: 'failure-t',
        order: 5,

        item: { kind: 'failure', turn_id: 't' },
      };
      yield terminal('generation_failed');
    });
    const states: string[] = [];
    const controller = new ConversationController(transport, (state) => {
      const row = contentOf(state).find((item) => item.kind === 'tool');
      if (row?.kind === 'tool') states.push(row.status);
    });
    await controller.start();
    const submission = controller.submit('Hello', vi.fn());
    await visible.promise;
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status).toBeNull();
    expect(contentOf(controller.state).map((item) => item.kind)).toEqual([
      'text',
      'intermediate',
      'tool',
      'text',
      'artifact',
    ]);
    expect(controller.state.turns[0]?.status).toBe('active');
    expect(states).toContain('requested');
    expect(states).toContain('running');
    expect(contentOf(controller.state).filter((item) => item.kind === 'tool')).toHaveLength(1);
    finish.resolve();
    await submission;
    expect(controller.state.composerDisabled).toBe(false);
    expect(contentOf(controller.state).map((item) => item.kind)).toEqual([
      'text',
      'intermediate',
      'tool',
      'text',
      'artifact',
      'failure',
    ]);
    expect(controller.state.status?.kind).toBe('error');
    expect(controller.state.turns[0]?.status).toBe('failed');
  });

  it.each(['eof', 'error', 'malformed'] as const)(
    'retains output and disables composer after %s without reconnect or retry',
    async (ending) => {
      const transport = new FakeTransport();
      transport.observeTurn.mockImplementation(async function* () {
        yield await Promise.resolve(initial());
        yield { ...tool('running', 3), order: 1 };
        if (ending === 'error') throw new Error('offline');
        if (ending === 'malformed') yield { ...tool('completed', 4), identity: 'wrong' };
      });
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(contentOf(controller.state)).toHaveLength(2);
      expect(controller.state.turns).toMatchObject([
        { id: 't', userMessageId: 'confirmed-0-user', status: 'unknown' },
      ]);
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status).not.toHaveProperty('action');
      await controller.performAction('retry-turn');
      await controller.submit('again', vi.fn());
      expect(transport.observeTurn).toHaveBeenCalledTimes(1);
      expect(transport.generateTurn).toHaveBeenCalledTimes(1);
      expect(transport.appendMessage).toHaveBeenCalledTimes(1);
      expect(transport.readSession).not.toHaveBeenCalled();
    },
  );

  it.each(['completed', 'generation_failed', 'conflict'] as const)(
    'retains the %s outcome and streamed content when accepting the next turn',
    async (outcome) => {
      const transport = new FakeTransport();
      const original = snapshot();
      transport.observeTurn.mockReturnValueOnce(
        stream([
          { kind: 'snapshot', turn_id: 't', snapshot: original },
          { ...tool('completed', 2), order: 1 },
          terminal(outcome),
        ]),
      );
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      const completedState = controller.state;
      transport.appendMessage.mockResolvedValueOnce({
        role: 'user',
        text: 'Next',
        turn_id: 'next',
      });
      transport.generateTurn.mockResolvedValueOnce({ kind: 'accepted', turn_id: 'next' });
      transport.observeTurn.mockReturnValueOnce(stream([]));
      await controller.submit('Next', vi.fn());
      expect(controller.state.turns.map((turn) => turn.status)).toEqual([
        outcome === 'completed' ? 'completed' : 'failed',
        'unknown',
      ]);
      expect(controller.state.turns[0].content).toEqual(completedState.turns[0].content);
      expect(controller.state.turns[0].content[1]).toMatchObject({
        kind: 'tool',
        status: 'completed',
      });
      expect(completedState.turns).toHaveLength(1);
      expect(original.turns[0].status).toBe('in_progress');
      expect(original.turns[0].timeline).toHaveLength(1);
      expect(controller.state.composerDisabled).toBe(true);
    },
  );

  it.each(['event', 'snapshot'] as const)(
    'retains closing from %s across omitted output and marks interrupted work unknown',
    async (source) => {
      const transport = new FakeTransport();
      transport.observeTurn.mockImplementation(async function* () {
        yield await Promise.resolve<StreamEvent>({
          kind: 'snapshot',
          turn_id: 't',
          snapshot: snapshot({
            turns: [
              { ...snapshot().turns[0], status: source === 'snapshot' ? 'closing' : 'in_progress' },
            ],
          }),
        });
        if (source === 'event') yield { kind: 'closing', turn_id: 't', sequence: 2 };
        expect(controller.state.turns[0].status).toBe('active');
        expect(controller.state.status).toBeNull();
        expect(controller.state.composerDisabled).toBe(true);
        yield {
          kind: 'upsert',
          turn_id: 't',
          sequence: 3,
          identity: 'omitted',
          order: 1,
          item: {
            kind: 'artifact',
            turn_id: 't',
            artifact: {
              artifact_id: 'omitted',
              turn_id: 't',
              type: 'custom',
              order: 1,
              created_at: '2026-10-18T10:00:00Z',
              payload: {},
            },
          },
        };
        expect(controller.state.status).toBeNull();
      });
      const controller = new ConversationController(
        transport,
        () => undefined,
        () => null,
      );
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.turns[0].status).toBe('unknown');
      expect(controller.state.turns[0].content).toHaveLength(1);
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status?.kind).toBe('error');
    },
  );

  it('accepts terminal-before-subscribe catch-up and uses terminal metadata rather than displayed text', async () => {
    const transport = new FakeTransport();
    transport.observeTurn.mockReturnValue(
      stream([
        {
          kind: 'snapshot',
          turn_id: 't',
          snapshot: snapshot({
            turns: [
              {
                turn_id: 't',
                user_message_id: 'confirmed-0-user',
                status: 'generation_failed',
                timeline: [
                  ...snapshot().turns[0].timeline,
                  {
                    kind: 'message',
                    turn_id: 't',
                    id: 'f',
                    role: 'assistant',
                    text: 'Final before failure',
                  },
                ],
              },
            ],
          }),
        },
        terminal('generation_failed'),
      ]),
    );
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.kind).toBe('error');
    expect(contentOf(controller.state)[1]).toMatchObject({ text: 'Final before failure' });
    expect(controller.state.turns).toMatchObject([
      { id: 't', userMessageId: 'confirmed-0-user', status: 'failed' },
    ]);
  });

  it.each(['completed', 'generation_failed', 'conflict'] as const)(
    'retains authoritative %s snapshot outcome when observation ends before terminal event',
    async (outcome) => {
      const transport = new FakeTransport();
      transport.observeTurn.mockReturnValue(
        stream([
          {
            kind: 'snapshot',
            turn_id: 't',
            snapshot: snapshot({
              turns: [
                {
                  turn_id: 't',
                  user_message_id: 'confirmed-0-user',
                  status: outcome,
                  timeline: [
                    ...snapshot().turns[0].timeline,
                    { kind: 'intermediate', id: 'detail', text: 'Received detail', turn_id: 't' },
                    {
                      kind: 'message',
                      role: 'assistant',
                      id: 'answer',
                      text: 'Received answer',
                      turn_id: 't',
                    },
                  ],
                },
              ],
            }),
          },
        ]),
      );
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.turns).toMatchObject([
        {
          id: 't',
          userMessageId: 'confirmed-0-user',
          status: outcome === 'completed' ? 'completed' : 'failed',
        },
      ]);
      expect(contentOf(controller.state).map((item) => item.id)).toEqual([
        'confirmed-0-user',
        'detail',
        'answer',
      ]);
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status?.kind).toBe('error');
    },
  );

  it('detaches and ignores stale events when replaced or disposed', async () => {
    const transport = new FakeTransport();
    const attached = deferred<void>();
    const finish = deferred<void>();
    let signal: AbortSignal | undefined;
    transport.observeTurn.mockImplementation(async function* (_id, _turn, current) {
      signal = current;
      yield initial();
      attached.resolve();
      await finish.promise;
      yield tool('completed', 4);
      yield terminal();
    });
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    const old = controller.submit('Hello', vi.fn());
    await attached.promise;
    await controller.start();
    expect(signal?.aborted).toBe(true);
    finish.resolve();
    await old;
    expect(contentOf(controller.state)).toEqual([]);
    controller.dispose();
    await controller.submit('ignored', vi.fn());
    expect(transport.appendMessage).toHaveBeenCalledTimes(1);
  });

  it.each(['publish', 'acknowledge'] as const)(
    'does not start an old turn when %s disposes the controller',
    async (source) => {
      const transport = new FakeTransport();
      const acknowledge = vi.fn(() => {
        if (source === 'acknowledge') controller.dispose();
      });
      const controller = new ConversationController(transport, (state) => {
        if (source === 'publish' && contentOf(state).length > 0) controller.dispose();
      });
      await controller.start();
      await controller.submit('Hello', acknowledge);
      expect(transport.generateTurn).not.toHaveBeenCalled();
      if (source === 'publish') expect(acknowledge).not.toHaveBeenCalled();
    },
  );

  it.each(['publish', 'acknowledge'] as const)(
    'does not start an old turn when reconciled %s disposes the controller',
    async (source) => {
      const transport = new FakeTransport();
      transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
      transport.readSession.mockResolvedValue(snapshot());
      const controller = new ConversationController(transport, (state) => {
        if (source === 'publish' && contentOf(state).length > 0) controller.dispose();
      });
      await controller.start();
      const acknowledge = vi.fn(() => {
        if (source === 'acknowledge') controller.dispose();
      });
      await controller.submit('Hello', acknowledge);
      expect(transport.generateTurn).not.toHaveBeenCalled();
      if (source === 'publish') expect(acknowledge).not.toHaveBeenCalled();
    },
  );

  it('ignores session creation completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<SessionCreationResponse>();
    transport.createSession.mockReturnValue(pending.promise);
    const publish = vi.fn();
    const controller = new ConversationController(transport, publish);
    const starting = controller.start();
    controller.dispose();
    publish.mockClear();
    pending.resolve({ session_id: 'old-owner', expires_at: '2026-10-04T20:00:00Z' });
    await starting;
    await controller.submit('ignored', vi.fn());
    expect(publish).not.toHaveBeenCalled();
    expect(transport.appendMessage).not.toHaveBeenCalled();
  });

  it('does not acknowledge or start work for an append completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<UserMessageResponse>();
    transport.appendMessage.mockReturnValue(pending.promise);
    const publish = vi.fn();
    const acknowledge = vi.fn();
    const controller = new ConversationController(transport, publish);
    await controller.start();
    const submitting = controller.submit('Hello', acknowledge);
    controller.dispose();
    publish.mockClear();
    pending.resolve({ role: 'user', text: 'Hello', turn_id: 't' });
    await submitting;
    expect(publish).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('does not attach an observer for turn admission completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<AcceptedTurnResponse>();
    const admitted = deferred<void>();
    transport.generateTurn.mockImplementation(() => {
      admitted.resolve();
      return pending.promise;
    });
    const publish = vi.fn();
    const controller = new ConversationController(transport, publish);
    await controller.start();
    const submitting = controller.submit('Hello', vi.fn());
    await admitted.promise;
    controller.dispose();
    publish.mockClear();
    pending.resolve({ kind: 'accepted', turn_id: 'old-owner-turn' });
    await submitting;
    expect(publish).not.toHaveBeenCalled();
    expect(transport.observeTurn).not.toHaveBeenCalled();
    expect(transport.readSession).not.toHaveBeenCalled();
  });

  it.each(['completed', 'generation_failed', 'conflict'] as const)(
    'recovers authoritative %s admission outcome without attaching another observer',
    async (outcome) => {
      const transport = new FakeTransport();
      transport.generateTurn.mockRejectedValue(new ConversationNetworkError('uncertain'));
      transport.readSession.mockResolvedValue(
        snapshot({
          turns: [
            {
              turn_id: 't',
              user_message_id: 'confirmed-0-user',
              status: outcome,
              timeline: [
                ...snapshot().turns[0].timeline,
                {
                  kind: 'message',
                  role: 'assistant',
                  id: 'answer',
                  text: 'Received',
                  turn_id: 't',
                },
              ],
            },
          ],
        }),
      );
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.turns).toMatchObject([
        {
          id: 't',
          userMessageId: 'confirmed-0-user',
          status: outcome === 'completed' ? 'completed' : 'failed',
        },
      ]);
      expect(contentOf(controller.state)[1]).toMatchObject({ id: 'answer', turnId: 't' });
      expect(controller.state.composerDisabled).toBe(false);
      expect(transport.observeTurn).not.toHaveBeenCalled();
    },
  );

  it('does not recover an older terminal turn when the latest submitted turn is pending', async () => {
    const transport = new FakeTransport();
    transport.generateTurn.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(
      snapshot({
        turns: [
          {
            turn_id: 'old',
            user_message_id: 'request-old',
            status: 'completed',
            timeline: [
              { kind: 'message', role: 'user', id: 'request-old', text: 'Old', turn_id: 'old' },
              {
                kind: 'message',
                role: 'assistant',
                id: 'old-answer',
                text: 'Done',
                turn_id: 'old',
              },
            ],
          },
          {
            turn_id: 'latest',
            user_message_id: 'request-latest',
            status: 'pending',
            timeline: [
              {
                kind: 'message',
                role: 'user',
                id: 'request-latest',
                text: 'Hello',
                turn_id: 'latest',
              },
            ],
          },
        ],
      }),
    );
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(controller.state.turns).toMatchObject([
      { id: 'old', userMessageId: 'request-old', status: 'completed' },
      { id: 'latest', userMessageId: 'request-latest', status: 'unknown' },
    ]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.kind).toBe('error');
    expect(transport.observeTurn).not.toHaveBeenCalled();
    expect(transport.generateTurn).toHaveBeenCalledTimes(1);
  });

  it('reconciles uncertain start once and observes the authoritative active turn without replacement execution', async () => {
    const transport = new FakeTransport();
    transport.generateTurn.mockRejectedValue(new ConversationNetworkError('offline'));
    transport.readSession.mockResolvedValue(snapshot());
    transport.observeTurn.mockReturnValue(stream([initial(), terminal()]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(transport.generateTurn).toHaveBeenCalledTimes(1);
    expect(transport.observeTurn).toHaveBeenCalledWith('s', 't', expect.any(AbortSignal));
    expect(controller.state.composerDisabled).toBe(false);
  });

  it('reconciles uncertain append using user history despite extra rendered messages', async () => {
    const transport = new FakeTransport();
    transport.observeTurn.mockReturnValue(
      stream([
        initial(),
        {
          kind: 'upsert',
          turn_id: 't',
          sequence: 2,
          identity: 'phase-less',
          order: 1,

          item: {
            kind: 'message',
            id: 'phase-less',
            role: 'assistant',
            turn_id: 't',
            text: 'Extra visible output',
          },
        },
        terminal(),
      ]),
    );
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    transport.appendMessage.mockRejectedValueOnce(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(
      snapshot({
        turns: [
          { ...snapshot().turns[0], status: 'completed' },
          {
            turn_id: 'next',
            user_message_id: 'confirmed-1-user',
            status: 'pending',
            timeline: [
              {
                kind: 'message',
                id: 'confirmed-1-user',
                role: 'user',
                text: 'Next',
                turn_id: 'next',
              },
            ],
          },
        ],
      }),
    );
    const acknowledge = vi.fn();
    await controller.submit('Next', acknowledge);
    expect(acknowledge).toHaveBeenCalledTimes(1);
    expect(transport.generateTurn).toHaveBeenCalledTimes(2);
  });

  it.each(['method_not_allowed', 'agent_unavailable', 'expired', 'limit_reached'] as const)(
    'preserves typed append %s state',
    async (kind) => {
      const transport = new FakeTransport();
      transport.appendMessage.mockRejectedValue(new ConversationApiError(409, kind));
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      const acknowledge = vi.fn();
      await controller.submit('Hello', acknowledge);
      expect(acknowledge).not.toHaveBeenCalled();
      expect(transport.generateTurn).not.toHaveBeenCalled();
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status?.kind).toBe('error');
    },
  );

  it('excludes concurrent submissions and acknowledges only accepted messages', async () => {
    const transport = new FakeTransport();
    const pending = deferred<UserMessageResponse>();
    transport.appendMessage.mockReturnValue(pending.promise);
    transport.observeTurn.mockReturnValue(stream([initial(), terminal()]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();
    const first = controller.submit('Hello', acknowledge);
    await controller.submit('second', vi.fn());
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.appendMessage).toHaveBeenCalledTimes(1);
    pending.resolve({ role: 'user', text: 'Hello', turn_id: 't' });
    await first;
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });
  it('retains the accepted turn with unknown outcome when observation ends before its snapshot', async () => {
    const transport = new FakeTransport();
    transport.observeTurn.mockReturnValue(stream([]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(controller.state.turns).toMatchObject([
      { id: 't', userMessageId: 'confirmed-0-user', status: 'unknown' },
    ]);
    expect(contentOf(controller.state)).toEqual([
      { kind: 'text', id: 'confirmed-0-user', role: 'user', text: 'Hello', turnId: 't' },
    ]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.kind).toBe('error');
    expect(transport.readSession).not.toHaveBeenCalled();
  });

  it.each(['expired', 'unknown', 'agent_unavailable', 'method_not_allowed'] as const)(
    'preserves typed pre-stream %s errors without reconnect',
    async (kind) => {
      const transport = new FakeTransport();
      transport.observeTurn.mockReturnValue({
        [Symbol.asyncIterator]: () => ({
          next: () => Promise.reject(new ConversationApiError(410, kind)),
        }),
      });
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status?.message).not.toContain('unbekannt');
      expect(controller.state.turns).toMatchObject([{ id: 't', status: 'unknown' }]);
      expect(transport.observeTurn).toHaveBeenCalledTimes(1);
      expect(transport.readSession).not.toHaveBeenCalled();
    },
  );

  it.each(['unavailable', 'observation_limit'] as const)(
    'distinguishes typed stream %s from confirmed turn failure',
    async (reason) => {
      const transport = new FakeTransport();
      transport.observeTurn.mockReturnValue(
        stream([initial(), { kind: 'error', turn_id: 't', reason }]),
      );
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.composerDisabled).toBe(true);
      if (reason === 'unavailable') expect(controller.state.status?.action?.id).toBe('new-session');
      else {
        expect(controller.state.status?.message).toContain('unbekannt');
        expect(controller.state.status).not.toHaveProperty('action');
      }
      expect(contentOf(controller.state)).toHaveLength(1);
    },
  );

  it.each(['replace', 'dispose'] as const)(
    'ignores a stale append reconciliation rejection after %s',
    async (operation) => {
      const transport = new FakeTransport();
      const reading = deferred<void>();
      let reject!: (reason: Error) => void;
      transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
      transport.readSession.mockImplementation(() => {
        reading.resolve();
        return new Promise((_resolve, fail) => {
          reject = fail;
        });
      });
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      const old = controller.submit('Hello', vi.fn());
      await reading.promise;
      if (operation === 'replace') await controller.start();
      else controller.dispose();
      const current = controller.state;
      reject(new ConversationNetworkError('old read failed'));
      await old;
      expect(controller.state).toBe(current);
      expect(transport.generateTurn).not.toHaveBeenCalled();
    },
  );

  it('retains custom artifact envelope mapping and omission under live updates', async () => {
    const transport = new FakeTransport();
    const events: StreamEvent[] = [initial()];
    for (const id of ['omitted', 'visible'])
      events.push({
        kind: 'upsert',
        turn_id: 't',
        identity: id,
        order: id === 'omitted' ? 1 : 2,
        sequence: id === 'omitted' ? 2 : 3,
        item: {
          kind: 'artifact',
          turn_id: 't',
          artifact: {
            artifact_id: id,
            turn_id: 't',
            type: 'custom',
            order: 7,
            created_at: '2026-10-04T18:00:00Z',
            payload: { value: id },
          },
        },
      });
    const statuses: (string | null)[] = [];
    transport.observeTurn.mockImplementation(async function* () {
      for (const event of events) {
        yield await Promise.resolve(event);
        statuses.push(controller.state.status?.kind ?? null);
      }
      yield terminal();
    });
    const mapper = vi.fn(
      (artifact: import('../generated/types.gen').PublishedArtifactDictStrObject) =>
        artifact.artifact_id === 'omitted'
          ? null
          : {
              kind: 'artifact' as const,
              id: `custom-${artifact.artifact_id}`,
              type: 'custom',
              headline: 'Mapped',
              payload: { value: 'visible' },
            },
    );
    const controller = new ConversationController(transport, () => undefined, mapper);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(contentOf(controller.state).map((item) => item.id)).toEqual([
      'confirmed-0-user',
      'custom-visible',
    ]);
    expect(statuses).toEqual(['loading', 'loading', null]);
    expect(mapper).toHaveBeenCalledWith(
      expect.objectContaining({ artifact_id: 'visible', order: 7, payload: { value: 'visible' } }),
    );
    expect(contentOf(controller.state)[1]).toMatchObject({ headline: 'Mapped', type: 'custom' });
  });

  describe.each(['observation', 'append-reconciliation', 'start-reconciliation'] as const)(
    'snapshot validation through %s',
    (source) => {
      it.each([
        'wrong-session',
        'wrong-turn',
        'wrong-anchor',
        'duplicate-identity',
        'duplicate-turn',
        'artifact-turn',
        'cross-turn-collision',
      ] as const)(
        'rejects %s from a custom transport before retaining its content',
        async (variant) => {
          const invalid = snapshot();
          const turn = invalid.turns[0];
          if (variant === 'wrong-session') invalid.session_id = 'other';
          if (variant === 'wrong-turn')
            turn.timeline.push({
              kind: 'intermediate',
              id: 'detail',
              text: 'Invalid output',
              turn_id: 'other',
            });
          if (variant === 'wrong-anchor') turn.user_message_id = 'missing';
          if (variant === 'duplicate-identity') turn.timeline.push({ ...turn.timeline[0] });
          if (variant === 'duplicate-turn') invalid.turns.push({ ...turn });
          if (variant === 'artifact-turn')
            turn.timeline.push({
              kind: 'artifact',
              turn_id: 't',
              artifact: {
                artifact_id: 'artifact',
                turn_id: 'other',
                type: 'json',
                order: 1,
                created_at: '2026-10-18T10:00:00Z',
                payload: { title: 'Invalid output', payload: {} },
              },
            });
          if (variant === 'cross-turn-collision')
            invalid.turns.push({
              turn_id: 'other',
              user_message_id: 'other-user',
              status: 'completed',
              timeline: [
                {
                  kind: 'message',
                  role: 'user',
                  id: 'other-user',
                  text: 'Other',
                  turn_id: 'other',
                },
                {
                  kind: 'intermediate',
                  id: turn.user_message_id,
                  text: 'Invalid output',
                  turn_id: 'other',
                },
              ],
            });
          const transport = new FakeTransport();
          if (source === 'observation') {
            transport.observeTurn.mockReturnValue(
              stream([{ kind: 'snapshot', turn_id: 't', snapshot: invalid }, terminal()]),
            );
          } else {
            transport.readSession.mockResolvedValue(invalid);
            if (source === 'append-reconciliation')
              transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
            else
              transport.generateTurn.mockRejectedValue(new ConversationNetworkError('uncertain'));
          }
          const controller = new ConversationController(transport, () => undefined);
          await controller.start();
          const acknowledge = vi.fn();
          await controller.submit('Hello', acknowledge);
          expect(controller.state.composerDisabled).toBe(true);
          expect(controller.state.status?.kind).toBe('error');
          if (source === 'append-reconciliation') {
            expect(controller.state.turns).toEqual([]);
            expect(acknowledge).not.toHaveBeenCalled();
            expect(transport.generateTurn).not.toHaveBeenCalled();
          } else {
            expect(controller.state.turns).toMatchObject([{ id: 't', status: 'unknown' }]);
            expect(controller.state.turns[0].content).toHaveLength(1);
            expect(acknowledge).toHaveBeenCalledOnce();
          }
          if (source !== 'observation') expect(transport.observeTurn).not.toHaveBeenCalled();
        },
      );
    },
  );

  it.each(['identity', 'turn', 'position', 'collision', 'artifact-turn'] as const)(
    'rejects an inconsistent turn-local upsert: %s',
    async (variant) => {
      const transport = new FakeTransport();
      const first = { ...tool('running', 2), order: 1 };
      const invalid: Extract<StreamEvent, { kind: 'upsert' }> =
        variant === 'artifact-turn'
          ? {
              kind: 'upsert',
              turn_id: 't',
              identity: 'a',
              order: 2,
              sequence: 3,
              item: {
                kind: 'artifact',
                turn_id: 't',
                artifact: {
                  artifact_id: 'a',
                  turn_id: 'other',
                  type: 'json',
                  order: 7,
                  created_at: '2026-10-18T10:00:00Z',
                  payload: { title: 'Data', payload: 1 },
                },
              },
            }
          : {
              ...tool('completed', 3),
              order: variant === 'position' ? 2 : variant === 'collision' ? 0 : 1,
              identity:
                variant === 'identity'
                  ? 'other'
                  : variant === 'collision'
                    ? 'tool-other'
                    : 'tool-e',
              item: {
                kind: 'tool',
                name: 'save',
                status: 'completed',
                turn_id: variant === 'turn' ? 'other' : 't',
                execution_id: variant === 'collision' ? 'other' : 'e',
              },
            };
      transport.observeTurn.mockReturnValue(stream([initial(), first, invalid, terminal()]));
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      await controller.submit('Hello', vi.fn());
      expect(controller.state.turns[0]?.status).toBe('unknown');
      expect(controller.state.composerDisabled).toBe(true);
      expect(contentOf(controller.state)).toHaveLength(2);
      expect(contentOf(controller.state)[1]).toMatchObject({ kind: 'tool', status: 'running' });
    },
  );

  it('applies local positions after historical turns and reconciles repeated identical submissions without duplication', async () => {
    const transport = new FakeTransport();
    const firstTurn = { ...snapshot().turns[0], status: 'completed' as const };
    const nextTurn = {
      turn_id: 'next',
      user_message_id: 'confirmed-1-user',
      status: 'pending' as const,
      timeline: [
        {
          kind: 'message' as const,
          role: 'user' as const,
          id: 'confirmed-1-user',
          text: 'Hello',
          turn_id: 'next',
        },
      ],
    };
    transport.observeTurn.mockReturnValueOnce(stream([initial(), terminal()]));
    transport.generateTurn
      .mockResolvedValueOnce({ kind: 'accepted', turn_id: 't' })
      .mockResolvedValueOnce({ kind: 'accepted', turn_id: 'next' });
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    transport.appendMessage.mockRejectedValueOnce(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(snapshot({ turns: [firstTurn, nextTurn] }));
    transport.observeTurn.mockImplementationOnce(async function* () {
      expect(contentOf(controller.state).map((item) => item.id)).toEqual([
        'confirmed-0-user',
        'confirmed-1-user',
      ]);
      yield await Promise.resolve<StreamEvent>({
        kind: 'snapshot',
        turn_id: 'next',
        snapshot: snapshot({ turns: [firstTurn, { ...nextTurn, status: 'in_progress' }] }),
      });
      yield {
        kind: 'upsert',
        turn_id: 'next',
        identity: 'detail-next',
        order: 1,
        sequence: 2,
        item: { kind: 'intermediate', turn_id: 'next', id: 'detail-next', text: 'Working' },
      };
      yield { ...terminal(), turn_id: 'next' };
    });
    const acknowledge = vi.fn();
    await controller.submit('Hello', acknowledge);
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(transport.generateTurn).toHaveBeenCalledTimes(2);
    expect(contentOf(controller.state).map((item) => item.id)).toEqual([
      'confirmed-0-user',
      'confirmed-1-user',
      'detail-next',
    ]);
    expect(controller.state.turns.map((turn) => turn.status)).toEqual(['completed', 'completed']);
    expect(controller.state.composerDisabled).toBe(false);
  });

  it('recovers from unavailable session creation with an explicitly requested new session', async () => {
    const transport = new FakeTransport();
    transport.createSession.mockRejectedValueOnce(
      new ConversationApiError(503, 'agent_unavailable'),
    );
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.action?.id).toBe('new-session');
    await controller.performAction('new-session');
    expect(contentOf(controller.state)).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(transport.createSession).toHaveBeenCalledTimes(2);
  });

  it('establishes an absent ambiguous append without acknowledgement or generation', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(snapshot({ turns: [] }));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();
    await controller.submit('Hello', acknowledge);
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.kind).toBe('error');
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it.each(['accepted', 'uncertain'] as const)(
    'uses the displayed turns after an unsuccessful reconciliation for a later %s append',
    async (outcome) => {
      const transport = new FakeTransport();
      const historicalTurn: SessionSnapshotResponse['turns'][number] = {
        ...snapshot().turns[0],
        status: 'completed',
        timeline: [
          { kind: 'message', id: 'historical-user', role: 'user', text: 'Earlier', turn_id: 't' },
        ],
        user_message_id: 'historical-user',
      };
      transport.appendMessage.mockRejectedValueOnce(new ConversationNetworkError('uncertain'));
      transport.readSession.mockResolvedValueOnce(snapshot({ turns: [historicalTurn] }));
      const controller = new ConversationController(transport, () => undefined);
      await controller.start();
      const firstAcknowledgement = vi.fn();
      await controller.submit('Hello', firstAcknowledgement);
      expect(firstAcknowledgement).not.toHaveBeenCalled();
      expect(controller.state.turns[0].content[0]).toMatchObject({ text: 'Earlier' });
      expect(controller.state.composerDisabled).toBe(false);
      expect(transport.generateTurn).not.toHaveBeenCalled();

      const nextTurn: SessionSnapshotResponse['turns'][number] = {
        turn_id: 'next',
        user_message_id: 'next-user',
        status: 'in_progress',
        timeline: [
          { kind: 'message', id: 'next-user', role: 'user', text: 'Hello', turn_id: 'next' },
        ],
      };
      const nextSnapshot = snapshot({ turns: [historicalTurn, nextTurn] });
      if (outcome === 'uncertain') {
        transport.appendMessage.mockRejectedValueOnce(new ConversationNetworkError('uncertain'));
        transport.readSession.mockResolvedValueOnce(nextSnapshot);
      } else {
        transport.appendMessage.mockResolvedValueOnce({
          role: 'user',
          text: 'Hello',
          turn_id: 'next',
        });
      }
      transport.generateTurn.mockResolvedValueOnce({ kind: 'accepted', turn_id: 'next' });
      transport.observeTurn.mockImplementationOnce(async function* () {
        expect(controller.state.turns).toHaveLength(2);
        expect(controller.state.turns[1].content[0]).toMatchObject({
          id: outcome === 'accepted' ? 'confirmed-1-user' : 'next-user',
          text: 'Hello',
        });
        yield await Promise.resolve<StreamEvent>({
          kind: 'snapshot',
          turn_id: 'next',
          snapshot: nextSnapshot,
        });
        yield { ...terminal(), turn_id: 'next' };
      });
      const acknowledgement = vi.fn();
      await controller.submit('Hello', acknowledgement);
      expect(acknowledgement).toHaveBeenCalledOnce();
      expect(transport.generateTurn).toHaveBeenCalledOnce();
      expect(controller.state.turns.map((turn) => turn.content.map((item) => item.id))).toEqual([
        ['historical-user'],
        ['next-user'],
      ]);
      expect(controller.state.composerDisabled).toBe(false);
    },
  );

  it('keeps ambiguous append disabled when authoritative state cannot be read', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockRejectedValue(new ConversationNetworkError('unavailable'));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(true);
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });
});

function contentOf(state: ConversationViewState): readonly ChatContent[] {
  return state.turns.flatMap((turn) => turn.content);
}
