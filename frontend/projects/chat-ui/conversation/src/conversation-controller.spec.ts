import { describe, expect, it, vi } from 'vitest';
import { ConversationController } from './conversation-controller';
import { ConversationApiError, ConversationNetworkError, type ConversationTransport } from './conversation-api';
import type { AcceptedTurnResponse, SessionCreationResponse, SessionSnapshotResponse, StreamEvent, StreamUpsert, UserMessageResponse } from '../generated/types.gen';

class FakeTransport implements ConversationTransport {
  createSession = vi.fn<() => Promise<SessionCreationResponse>>().mockResolvedValue({ session_id: 's', expires_at: '2026-10-04T20:00:00Z' });
  readSession = vi.fn<(id: string) => Promise<SessionSnapshotResponse>>();
  appendMessage = vi.fn<(id: string, text: string) => Promise<UserMessageResponse>>().mockResolvedValue({ role: 'user', text: 'Hello', turn_id: null });
  generateTurn = vi.fn<(id: string) => Promise<AcceptedTurnResponse>>().mockResolvedValue({ kind: 'accepted', turn_id: 't' });
  observeTurn = vi.fn<(id: string, turn: string, signal: AbortSignal) => AsyncIterable<StreamEvent>>();
}
function snapshot(overrides: Partial<SessionSnapshotResponse> = {}): SessionSnapshotResponse {
  return { session_id: 's', expires_at: '2026-10-04T20:00:00Z', messages: [{ role: 'user', text: 'Hello', turn_id: null }], artifacts: [],
    active_turn_id: 't', active_turn_status: 'in_progress', sequence: 1, terminal_turn_id: null, terminal_turn_kind: null,
    timeline: [{ kind: 'message', role: 'user', id: 'confirmed-0-user', text: 'Hello', turn_id: 't' }], ...overrides };
}
const initial = (): StreamEvent => ({ kind: 'snapshot', turn_id: 't', snapshot: snapshot() });
const terminal = (outcome: 'completed' | 'generation_failed' = 'completed'): StreamEvent => ({ kind: 'terminal', turn_id: 't', sequence: 10, outcome });
const tool = (status: 'requested' | 'running' | 'completed', sequence: number): Extract<StreamEvent, { kind: 'upsert' }> => ({
  kind: 'upsert', turn_id: 't', sequence, identity: 'tool-e', order: 2, artifact: null,
  item: { kind: 'tool', turn_id: 't', execution_id: 'e', name: 'save', status },
});
async function* stream(events: readonly StreamEvent[]): AsyncIterable<StreamEvent> { yield* events; }
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe('live conversation controller', () => {
  it.each(['event', 'snapshot'] as const)('hides progress on backend closing %s and keeps submission disabled until terminal failure', async (source) => {
    const transport = new FakeTransport();
    const visible = deferred<void>(); const finish = deferred<void>();
    transport.observeTurn.mockImplementation(async function* () {
      yield { kind: 'snapshot', turn_id: 't', snapshot: snapshot({
        active_turn_status: source === 'snapshot' ? 'closing' : 'in_progress',
        timeline: [{ kind: 'message', turn_id: 't', id: 'answer', role: 'assistant', text: 'Retained answer' }],
      }) };
      if (source === 'event') yield { kind: 'closing', turn_id: 't', sequence: 2 };
      yield tool('running', 3);
      visible.resolve(); await finish.promise;
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
    finish.resolve(); await submission;
    expect(controller.state.status?.kind).toBe('error');
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.content[0]).toMatchObject({ text: 'Retained answer' });
  });

  it('shows complete messages while busy, preserves all styles/output on failure, and upserts without regression', async () => {
    const transport = new FakeTransport();
    const visible = deferred<void>(); const finish = deferred<void>();
    transport.observeTurn.mockImplementation(async function* () {
      yield initial();
      yield { kind: 'upsert', turn_id: 't', sequence: 2, identity: 'commentary', order: 1, artifact: null,
        item: { kind: 'intermediate', turn_id: 't', id: 'commentary', text: 'Checking' } };
      yield tool('requested', 3); yield tool('running', 4); yield tool('requested', 3); yield tool('completed', 5);
      yield { kind: 'upsert', turn_id: 't', sequence: 6, identity: 'final', order: 3, artifact: null,
        item: { kind: 'message', turn_id: 't', id: 'final', role: 'assistant', text: 'Looks complete' } };
      yield { kind: 'upsert', turn_id: 't', sequence: 7, identity: 'a', order: 4,
        item: { kind: 'artifact', turn_id: 't', artifact_id: 'a' },
        artifact: { artifact_id: 'a', type: 'json', created_at: '2026-10-04T18:00:00Z', turn_id: 't', order: 4, payload: { title: 'Data', payload: { value: 1 } } } };
      visible.resolve(); await finish.promise;
      yield { kind: 'upsert', turn_id: 't', sequence: 8, identity: 'failure-t', order: 5, artifact: null, item: { kind: 'failure', turn_id: 't' } };
      yield terminal('generation_failed');
    });
    const states: string[] = [];
    const controller = new ConversationController(transport, (state) => {
      const row = state.content.find((item) => item.kind === 'tool');
      if (row?.kind === 'tool') states.push(row.status);
    });
    await controller.start();
    const submission = controller.submit('Hello', vi.fn());
    await visible.promise;
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.kind).toBe('loading');
    expect(controller.state.content.map((item) => item.kind)).toEqual(['text', 'intermediate', 'tool', 'text', 'artifact']);
    expect(states).toContain('requested'); expect(states).toContain('running');
    expect(controller.state.content.filter((item) => item.kind === 'tool')).toHaveLength(1);
    finish.resolve(); await submission;
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.content.map((item) => item.kind)).toEqual(['text', 'intermediate', 'tool', 'text', 'artifact', 'failure']);
    expect(controller.state.status?.kind).toBe('error');
  });

  it.each(['eof', 'error', 'malformed'] as const)('retains output and disables composer after %s without reconnect or retry', async (ending) => {
    const transport = new FakeTransport();
    transport.observeTurn.mockImplementation(async function* () {
      yield initial(); yield tool('running', 3);
      if (ending === 'error') throw new Error('offline');
      if (ending === 'malformed') yield { ...tool('completed', 4), identity: 'wrong' };
    });
    const controller = new ConversationController(transport, () => undefined);
    await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.content).toHaveLength(2);
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status).not.toHaveProperty('action');
    await controller.performAction('retry-turn'); await controller.submit('again', vi.fn());
    expect(transport.observeTurn).toHaveBeenCalledTimes(1);
    expect(transport.generateTurn).toHaveBeenCalledTimes(1);
    expect(transport.appendMessage).toHaveBeenCalledTimes(1);
    expect(transport.readSession).not.toHaveBeenCalled();
  });

  it('accepts terminal-before-subscribe catch-up and uses terminal metadata rather than displayed text', async () => {
    const transport = new FakeTransport();
    transport.observeTurn.mockReturnValue(stream([{ kind: 'snapshot', turn_id: 't', snapshot: snapshot({ active_turn_id: null, active_turn_status: null, terminal_turn_id: 't', terminal_turn_kind: 'generation_failed',
      timeline: [{ kind: 'message', turn_id: 't', id: 'f', role: 'assistant', text: 'Final before failure' }] }) }, terminal('generation_failed')]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(false); expect(controller.state.status?.kind).toBe('error');
    expect(controller.state.content[0]).toMatchObject({ text: 'Final before failure' });
  });

  it('detaches and ignores stale events when replaced or disposed', async () => {
    const transport = new FakeTransport(); const attached = deferred<void>(); const finish = deferred<void>();
    let signal: AbortSignal | undefined;
    transport.observeTurn.mockImplementation(async function* (_id, _turn, current) {
      signal = current; yield initial(); attached.resolve(); await finish.promise; yield tool('completed', 4); yield terminal();
    });
    const controller = new ConversationController(transport, () => undefined);
    await controller.start(); const old = controller.submit('Hello', vi.fn()); await attached.promise;
    await controller.start(); expect(signal?.aborted).toBe(true);
    finish.resolve(); await old; expect(controller.state.content).toEqual([]);
    controller.dispose(); await controller.submit('ignored', vi.fn()); expect(transport.appendMessage).toHaveBeenCalledTimes(1);
  });

  it.each(['publish', 'acknowledge'] as const)('does not start an old turn when %s disposes the controller', async (source) => {
    const transport = new FakeTransport();
    const acknowledge = vi.fn(() => { if (source === 'acknowledge') controller.dispose(); });
    const controller = new ConversationController(transport, (state) => {
      if (source === 'publish' && state.content.length > 0) controller.dispose();
    });
    await controller.start();
    await controller.submit('Hello', acknowledge);
    expect(transport.generateTurn).not.toHaveBeenCalled();
    if (source === 'publish') expect(acknowledge).not.toHaveBeenCalled();
  });

  it.each(['publish', 'acknowledge'] as const)('does not start an old turn when reconciled %s disposes the controller', async (source) => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(snapshot());
    const controller = new ConversationController(transport, (state) => {
      if (source === 'publish' && state.content.length > 0) controller.dispose();
    });
    await controller.start();
    const acknowledge = vi.fn(() => { if (source === 'acknowledge') controller.dispose(); });
    await controller.submit('Hello', acknowledge);
    expect(transport.generateTurn).not.toHaveBeenCalled();
    if (source === 'publish') expect(acknowledge).not.toHaveBeenCalled();
  });

  it('ignores session creation completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<SessionCreationResponse>();
    transport.createSession.mockReturnValue(pending.promise);
    const publish = vi.fn();
    const controller = new ConversationController(transport, publish);
    const starting = controller.start();
    controller.dispose(); publish.mockClear();
    pending.resolve({ session_id: 'old-owner', expires_at: '2026-10-04T20:00:00Z' });
    await starting; await controller.submit('ignored', vi.fn());
    expect(publish).not.toHaveBeenCalled();
    expect(transport.appendMessage).not.toHaveBeenCalled();
  });

  it('does not acknowledge or start work for an append completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<UserMessageResponse>();
    transport.appendMessage.mockReturnValue(pending.promise);
    const publish = vi.fn(); const acknowledge = vi.fn();
    const controller = new ConversationController(transport, publish);
    await controller.start();
    const submitting = controller.submit('Hello', acknowledge);
    controller.dispose(); publish.mockClear();
    pending.resolve({ role: 'user', text: 'Hello', turn_id: null });
    await submitting;
    expect(publish).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('does not attach an observer for turn admission completed after disposal', async () => {
    const transport = new FakeTransport();
    const pending = deferred<AcceptedTurnResponse>(); const admitted = deferred<void>();
    transport.generateTurn.mockImplementation(() => { admitted.resolve(); return pending.promise; });
    const publish = vi.fn();
    const controller = new ConversationController(transport, publish);
    await controller.start();
    const submitting = controller.submit('Hello', vi.fn());
    await admitted.promise;
    controller.dispose(); publish.mockClear();
    pending.resolve({ kind: 'accepted', turn_id: 'old-owner-turn' });
    await submitting;
    expect(publish).not.toHaveBeenCalled();
    expect(transport.observeTurn).not.toHaveBeenCalled();
    expect(transport.readSession).not.toHaveBeenCalled();
  });

  it('reconciles uncertain start once and observes the authoritative active turn without replacement execution', async () => {
    const transport = new FakeTransport(); transport.generateTurn.mockRejectedValue(new ConversationNetworkError('offline'));
    transport.readSession.mockResolvedValue(snapshot()); transport.observeTurn.mockReturnValue(stream([initial(), terminal()]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start(); await controller.submit('Hello', vi.fn());
    expect(transport.generateTurn).toHaveBeenCalledTimes(1); expect(transport.observeTurn).toHaveBeenCalledWith('s', 't', expect.any(AbortSignal));
    expect(controller.state.composerDisabled).toBe(false);
  });

  it('reconciles uncertain append using user history despite extra rendered messages', async () => {
    const transport = new FakeTransport();
    transport.observeTurn.mockReturnValue(stream([initial(), { kind: 'upsert', turn_id: 't', sequence: 2, identity: 'phase-less', order: 1, artifact: null,
      item: { kind: 'message', id: 'phase-less', role: 'assistant', turn_id: 't', text: 'Extra visible output' } }, terminal()]));
    const controller = new ConversationController(transport, () => undefined);
    await controller.start(); await controller.submit('Hello', vi.fn());
    transport.appendMessage.mockRejectedValueOnce(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(snapshot({ messages: [
      { role: 'user', text: 'Hello', turn_id: null }, { role: 'assistant', text: 'Canonical answer', turn_id: 't' }, { role: 'user', text: 'Next', turn_id: null },
    ] }));
    const acknowledge = vi.fn(); await controller.submit('Next', acknowledge);
    expect(acknowledge).toHaveBeenCalledTimes(1); expect(transport.generateTurn).toHaveBeenCalledTimes(2);
  });

  it.each(['method_not_allowed', 'agent_unavailable', 'expired', 'limit_reached'] as const)('preserves typed append %s state', async (kind) => {
    const transport = new FakeTransport(); transport.appendMessage.mockRejectedValue(new ConversationApiError(409, kind));
    const controller = new ConversationController(transport, () => undefined); await controller.start();
    const acknowledge = vi.fn(); await controller.submit('Hello', acknowledge);
    expect(acknowledge).not.toHaveBeenCalled(); expect(transport.generateTurn).not.toHaveBeenCalled();
    expect(controller.state.composerDisabled).toBe(true); expect(controller.state.status?.kind).toBe('error');
  });

  it('excludes concurrent submissions and acknowledges only accepted messages', async () => {
    const transport = new FakeTransport(); const pending = deferred<UserMessageResponse>(); transport.appendMessage.mockReturnValue(pending.promise);
    transport.observeTurn.mockReturnValue(stream([initial(), terminal()]));
    const controller = new ConversationController(transport, () => undefined); await controller.start(); const acknowledge = vi.fn();
    const first = controller.submit('Hello', acknowledge); await controller.submit('second', vi.fn());
    expect(acknowledge).not.toHaveBeenCalled(); expect(transport.appendMessage).toHaveBeenCalledTimes(1);
    pending.resolve({ role: 'user', text: 'Hello', turn_id: null }); await first; expect(acknowledge).toHaveBeenCalledTimes(1);
  });
  it.each(['expired', 'unknown', 'agent_unavailable', 'method_not_allowed'] as const)('preserves typed pre-stream %s errors without reconnect', async (kind) => {
    const transport = new FakeTransport();
    transport.observeTurn.mockImplementation(async function* () { throw new ConversationApiError(410, kind); });
    const controller = new ConversationController(transport, () => undefined); await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).not.toContain('unbekannt');
    expect(transport.observeTurn).toHaveBeenCalledTimes(1); expect(transport.readSession).not.toHaveBeenCalled();
  });

  it.each(['unavailable', 'observation_limit'] as const)('distinguishes typed stream %s from confirmed turn failure', async (reason) => {
    const transport = new FakeTransport(); transport.observeTurn.mockReturnValue(stream([initial(), { kind: 'error', turn_id: 't', reason }]));
    const controller = new ConversationController(transport, () => undefined); await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(true);
    if (reason === 'unavailable') expect(controller.state.status?.action?.id).toBe('new-session');
    else { expect(controller.state.status?.message).toContain('unbekannt'); expect(controller.state.status).not.toHaveProperty('action'); }
    expect(controller.state.content).toHaveLength(1);
  });

  it.each(['replace', 'dispose'] as const)('ignores a stale append reconciliation rejection after %s', async (operation) => {
    const transport = new FakeTransport(); const reading = deferred<void>();
    let reject!: (reason: Error) => void;
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockImplementation(() => { reading.resolve(); return new Promise((_resolve, fail) => { reject = fail; }); });
    const controller = new ConversationController(transport, () => undefined); await controller.start();
    const old = controller.submit('Hello', vi.fn()); await reading.promise;
    if (operation === 'replace') await controller.start(); else controller.dispose();
    const current = controller.state; reject(new ConversationNetworkError('old read failed')); await old;
    expect(controller.state).toBe(current); expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('retains custom artifact envelope mapping and omission under live updates', async () => {
    const transport = new FakeTransport();
    const events: StreamEvent[] = [initial()];
    for (const id of ['omitted', 'visible']) events.push({ kind: 'upsert', turn_id: 't', identity: id, order: id === 'omitted' ? 1 : 2, sequence: id === 'omitted' ? 2 : 3,
      item: { kind: 'artifact', turn_id: 't', artifact_id: id },
      artifact: { artifact_id: id, turn_id: 't', type: 'custom', order: 7, created_at: '2026-10-04T18:00:00Z', payload: { value: id } } });
    transport.observeTurn.mockReturnValue(stream([...events, terminal()]));
    const mapper = vi.fn((artifact: import('../generated/types.gen').ArtifactResponse) => artifact.artifact_id === 'omitted' ? null : {
      kind: 'artifact' as const, id: artifact.artifact_id, type: 'custom', headline: 'Mapped', payload: { value: 'visible' },
    });
    const controller = new ConversationController(transport, () => undefined, mapper); await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.content.map((item) => item.id)).toEqual(['confirmed-0-user', 'visible']);
    expect(mapper).toHaveBeenCalledWith(expect.objectContaining({ artifact_id: 'visible', order: 7, payload: { value: 'visible' } }));
    expect(controller.state.content[1]).toMatchObject({ headline: 'Mapped', type: 'custom' });
  });

  it('recovers from unavailable session creation with an explicitly requested new session', async () => {
    const transport = new FakeTransport(); transport.createSession.mockRejectedValueOnce(new ConversationApiError(503, 'agent_unavailable'));
    const controller = new ConversationController(transport, () => undefined); await controller.start();
    expect(controller.state.composerDisabled).toBe(true); expect(controller.state.status?.action?.id).toBe('new-session');
    await controller.performAction('new-session'); expect(controller.state.content).toEqual([]); expect(controller.state.composerDisabled).toBe(false);
    expect(transport.createSession).toHaveBeenCalledTimes(2);
  });

  it('establishes an absent ambiguous append without acknowledgement or generation', async () => {
    const transport = new FakeTransport(); transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockResolvedValue(snapshot({ messages: [], timeline: [], active_turn_id: null }));
    const controller = new ConversationController(transport, () => undefined); await controller.start(); const acknowledge = vi.fn();
    await controller.submit('Hello', acknowledge);
    expect(controller.state.composerDisabled).toBe(false); expect(controller.state.status?.kind).toBe('error');
    expect(acknowledge).not.toHaveBeenCalled(); expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('keeps ambiguous append disabled when authoritative state cannot be read', async () => {
    const transport = new FakeTransport(); transport.appendMessage.mockRejectedValue(new ConversationNetworkError('uncertain'));
    transport.readSession.mockRejectedValue(new ConversationNetworkError('unavailable'));
    const controller = new ConversationController(transport, () => undefined); await controller.start(); await controller.submit('Hello', vi.fn());
    expect(controller.state.composerDisabled).toBe(true); expect(transport.generateTurn).not.toHaveBeenCalled();
  });

});
