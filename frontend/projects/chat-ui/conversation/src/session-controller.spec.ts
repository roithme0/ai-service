import { afterEach, describe, expect, it, vi } from 'vitest';
import type {
  PresentedSession,
  SessionCreated,
  SessionEvent,
  TurnAccepted,
} from '../generated/types.gen';
import type { SessionTransport } from './session-transport';
import { SessionHttpError, SessionTransportError } from './session-transport';
import { SessionController } from './session-controller';

const time = '2026-10-21T12:00:00Z';
function snapshot(
  status?: 'running' | 'completed' | 'failed' | 'cancelled',
  prompt = true,
): PresentedSession {
  return {
    error: null,
    session_id: 'session',
    expires_at: time,
    history:
      status === undefined
        ? []
        : [
            ...(prompt ? [{ part_kind: 'user-prompt' as const, content: 'same' }] : []),
            {
              part_kind: 'turn',
              lifecycle: {
                run_id: 'run',
                started_at: time,
                finished_at: status === 'running' ? null : time,
                status,
              },
              parts: [],
            },
          ],
  };
}
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
class Transport implements SessionTransport {
  createSession = vi
    .fn<() => Promise<SessionCreated>>()
    .mockResolvedValue({ session_id: 'session', expires_at: time });
  readSession = vi.fn<(id: string) => Promise<PresentedSession>>();
  submitPrompt = vi
    .fn<(id: string, text: string) => Promise<TurnAccepted>>()
    .mockResolvedValue({ kind: 'accepted' });
  signal: AbortSignal | null = null;
  private queue: (SessionEvent | null)[] = [];
  private wake: (() => void) | null = null;
  emit(value: PresentedSession): void {
    this.queue.push({ kind: 'snapshot', snapshot: value });
    this.wake?.();
  }
  error(reason: Extract<SessionEvent, { kind: 'error' }>['reason']): void {
    this.queue.push({ kind: 'error', reason });
    this.wake?.();
  }
  end(): void {
    this.queue.push(null);
    this.wake?.();
  }
  async *observeSession(_id: string, signal: AbortSignal): AsyncIterable<SessionEvent> {
    this.signal = signal;
    signal.addEventListener('abort', () => this.wake?.(), { once: true });
    while (!signal.aborted) {
      if (this.queue.length === 0)
        await new Promise<void>((resolve) => {
          this.wake = resolve;
        });
      const event = this.queue.shift();
      if (event === null) return;
      if (event !== undefined) yield event;
    }
  }
}
async function flush(): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}
async function setup(): Promise<{ transport: Transport; controller: SessionController }> {
  const transport = new Transport();
  const controller = new SessionController(transport, vi.fn());
  await controller.start();
  transport.emit(snapshot());
  await flush();
  return { transport, controller };
}

describe('SessionController', () => {
  it.each(['snapshot', 'admission'] as const)(
    'offers new-session recovery when a session exhausted through %s becomes unavailable',
    async (source) => {
      const { transport, controller } = await setup();
      if (source === 'snapshot') {
        transport.emit({ ...snapshot('completed'), error: 'conversation_limit_reached' });
        await flush();
      } else {
        transport.submitPrompt.mockRejectedValueOnce(
          new SessionHttpError(409, 'conversation_limit_reached'),
        );
        await controller.submit('Rejected', vi.fn());
      }
      const retainedSnapshot = controller.state.snapshot;
      transport.error('unknown');
      await flush();
      expect(controller.state.snapshot).toBe(retainedSnapshot);
      expect(controller.state.status?.message).toContain(
        'Diese Unterhaltung ist nicht mehr verf\u00fcgbar.',
      );
      expect(controller.state.status?.action).toEqual({
        id: 'new-session',
        label: 'Neue Unterhaltung starten',
      });
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.observation).toBe('lost');
      expect(transport.signal?.aborted).toBe(true);
      await controller.performAction('new-session');
      transport.emit(snapshot());
      await flush();
      expect(transport.createSession).toHaveBeenCalledTimes(2);
      expect(controller.state.composerDisabled).toBe(false);
      expect(controller.state.status).toBeNull();
      controller.dispose();
    },
  );

  it('shows a later compatibility failure instead of stale exhaustion', async () => {
    const transport = new Transport();
    vi.spyOn(transport, 'observeSession').mockImplementation(async function* () {
      await Promise.resolve();
      yield {
        kind: 'snapshot',
        snapshot: { ...snapshot('completed'), error: 'conversation_limit_reached' },
      };
      throw new SessionHttpError(405, 'method_not_allowed');
    });
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    await flush();
    expect(controller.state.snapshot?.error).toBe('conversation_limit_reached');
    expect(controller.state.status).toEqual({
      kind: 'error',
      placement: 'assistant',
      message: 'App und Backend sind nicht kompatibel.',
    });
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.observation).toBe('lost');
    controller.dispose();
  });

  it('keeps exhausted history visible and disables submission through the existing error status', async () => {
    const { transport, controller } = await setup();
    const exhausted = { ...snapshot('completed'), error: 'conversation_limit_reached' as const };
    transport.emit(exhausted);
    await flush();
    expect(controller.state.snapshot).toEqual(exhausted);
    expect(controller.state.turns[0]?.content[0]).toMatchObject({ text: 'same', role: 'user' });
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status).toEqual({
      kind: 'error',
      placement: 'assistant',
      message: 'Conversation limit reached',
    });
    await controller.submit('Rejected', vi.fn());
    expect(transport.submitPrompt).not.toHaveBeenCalled();
    controller.dispose();
  });

  it('blocks admission after a limit rejection before the exhausted snapshot arrives', async () => {
    const { transport, controller } = await setup();
    transport.submitPrompt.mockRejectedValueOnce(
      new SessionHttpError(409, 'conversation_limit_reached'),
    );
    await controller.submit('Rejected', vi.fn());
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).toBe('Conversation limit reached');
    expect(controller.state.observation).toBe('connected');
    expect(transport.signal?.aborted).toBe(false);
    await controller.submit('Rejected again', vi.fn());
    expect(transport.submitPrompt).toHaveBeenCalledOnce();
    await controller.start();
    transport.emit(snapshot());
    await flush();
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status).toBeNull();
    controller.dispose();
  });

  it('acknowledges admission without inserting history or a sending indicator; waits for captured content', async () => {
    const { transport, controller } = await setup();
    const accepted = deferred<TurnAccepted>();
    transport.submitPrompt.mockReturnValueOnce(accepted.promise);
    const acknowledge = vi.fn();
    const pending = controller.submit('same', acknowledge);
    expect(controller.state.status).toBeNull();
    expect(controller.state.turns).toEqual([]);
    expect(controller.state.composerEditingDisabled).toBe(true);
    accepted.resolve({ kind: 'accepted' });
    await pending;
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(controller.state.turns).toEqual([]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.composerEditingDisabled).toBe(false);
    transport.emit(snapshot('running', false));
    await flush();
    expect(controller.state.status).toBeNull();
    transport.emit(snapshot('running'));
    await flush();
    expect(controller.state.status?.kind).toBe('loading');
    transport.emit(snapshot('completed'));
    await flush();
    expect(controller.state.composerDisabled).toBe(false);
    expect(transport.readSession).not.toHaveBeenCalled();
    controller.dispose();
  });

  it('renders snapshots arriving before admission acknowledgement without guessing acceptance', async () => {
    const { transport, controller } = await setup();
    const accepted = deferred<TurnAccepted>();
    transport.submitPrompt.mockReturnValueOnce(accepted.promise);
    const acknowledge = vi.fn();
    const pending = controller.submit('same', acknowledge);
    transport.emit(snapshot('completed'));
    await flush();
    expect(controller.state.turns).toHaveLength(2);
    expect(acknowledge).not.toHaveBeenCalled();
    expect(controller.state.composerDisabled).toBe(true);
    accepted.resolve({ kind: 'accepted' });
    await pending;
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(controller.state.composerDisabled).toBe(false);
    controller.dispose();
  });

  it('keeps draft and uncertainty after a lost response despite authoritative execution outcomes', async () => {
    const { transport, controller } = await setup();
    const accepted = deferred<TurnAccepted>();
    transport.submitPrompt.mockReturnValueOnce(accepted.promise);
    const acknowledge = vi.fn();
    const pending = controller.submit('same', acknowledge);
    transport.emit(snapshot('completed'));
    await flush();
    accepted.reject(new SessionTransportError('network'));
    await pending;
    transport.emit(snapshot('completed'));
    await flush();
    expect(controller.state.admission).toBe('uncertain');
    expect(controller.state.turns[1].status).toBe('completed');
    expect(controller.state.status?.message).toContain('angenommen wurde, ist unbekannt');
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.composerEditingDisabled).toBe(false);
    await controller.submit('same', acknowledge);
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.submitPrompt).toHaveBeenCalledOnce();
    expect(transport.readSession).not.toHaveBeenCalled();
    controller.dispose();
  });

  it.each(['running', 'completed', 'failed', 'cancelled'] as const)(
    'preserves %s execution independently of observation loss',
    async (status) => {
      const { transport, controller } = await setup();
      transport.emit(snapshot(status));
      transport.end();
      await flush();
      expect(controller.state.observation).toBe('lost');
      expect(controller.state.snapshot?.history.at(-1)).toMatchObject({ lifecycle: { status } });
      expect(controller.state.turns[1].status).toBe(status === 'running' ? 'unknown' : status);
      expect(controller.state.composerDisabled).toBe(true);
      expect(transport.signal?.aborted).toBe(false);
      controller.dispose();
    },
  );

  it.each(['failed', 'cancelled'] as const)(
    'keeps admission uncertainty first while retaining session loss and a %s outcome',
    async (status) => {
      const { transport, controller } = await setup();
      transport.submitPrompt.mockRejectedValueOnce(new SessionTransportError('network'));
      const acknowledge = vi.fn();
      await controller.submit('same', acknowledge);

      transport.emit(snapshot(status));
      transport.error('unknown');
      await flush();

      const outcome =
        status === 'failed'
          ? 'Die Antwort konnte nicht erstellt werden.'
          : 'Die Antwort wurde abgebrochen.';
      expect(controller.state.status?.message).toBe(
        'Ob die Nachricht angenommen wurde, ist unbekannt. Weitere Nachrichten sind deaktiviert. ' +
          'Diese Unterhaltung ist nicht mehr verf\u00fcgbar. ' +
          outcome,
      );
      expect(controller.state.status?.action?.id).toBe('new-session');
      expect(controller.state.turns[1].status).toBe(status);
      expect(controller.state.admission).toBe('uncertain');
      expect(controller.state.composerDisabled).toBe(true);
      expect(acknowledge).not.toHaveBeenCalled();
      controller.dispose();
    },
  );

  it('distinguishes rejected admission and setup failure without inventing prompts', async () => {
    const { transport, controller } = await setup();
    transport.submitPrompt.mockRejectedValueOnce(new SessionHttpError(400, 'invalid_input'));
    const acknowledge = vi.fn();
    await controller.submit('same', acknowledge);
    expect(controller.state.admission).toBe('rejected');
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.turns).toEqual([]);
    expect(acknowledge).not.toHaveBeenCalled();
    await controller.submit('same', acknowledge);
    transport.emit(snapshot('failed', false));
    await flush();
    expect(controller.state.turns).toHaveLength(1);
    expect(controller.state.turns[0].content).toMatchObject([{ kind: 'failure' }]);
    expect(controller.state.status?.message).toContain('Antwort konnte nicht');
    expect(controller.state.composerDisabled).toBe(false);
    controller.dispose();
  });

  it('waits for new prompt fragments on subsequent submissions and retains historical failures', async () => {
    const { transport, controller } = await setup();
    transport.emit(snapshot('failed'));
    await flush();
    await controller.submit('same', vi.fn());
    expect(controller.state.status).toBeNull();
    const previous = snapshot('failed').history;
    const active = {
      ...snapshot('running', false).history[0],
      lifecycle: {
        run_id: null,
        status: 'running' as const,
        started_at: time,
        finished_at: null,
      },
    };
    const gap: PresentedSession = { ...snapshot(), history: [...previous, active] };
    transport.emit(gap);
    await flush();
    expect(controller.state.status).toBeNull();
    expect(controller.state.turns[1].content).toMatchObject([{ kind: 'failure' }]);
    transport.emit({
      ...gap,
      history: [...previous, { part_kind: 'user-prompt', content: ['same', 'same'] }, active],
    });
    await flush();
    expect(controller.state.status?.kind).toBe('loading');
    controller.dispose();
  });

  it('offers explicit new-session recovery after creation failure and preserves initialization', async () => {
    const transport = new Transport();
    transport.createSession.mockRejectedValueOnce(new SessionHttpError(503, 'agent_unavailable'));
    const controller = new SessionController(transport, vi.fn());
    await controller.start({ initial_context: { source: 'test' } });
    expect(controller.state.status?.message).toBe('Der KI-Agent ist derzeit nicht verfügbar.');
    expect(controller.state.status?.action?.id).toBe('new-session');
    expect(controller.state.composerDisabled).toBe(true);
    await controller.performAction('new-session');
    expect(transport.createSession).toHaveBeenCalledTimes(2);
    expect(transport.createSession).toHaveBeenLastCalledWith({
      initial_context: { source: 'test' },
    });
    controller.dispose();
  });

  it('treats incompatible session creation as terminal without offering a retry', async () => {
    const transport = new Transport();
    transport.createSession.mockRejectedValueOnce(new SessionHttpError(405, 'method_not_allowed'));
    const observe = vi.spyOn(transport, 'observeSession');
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    expect(controller.state.status?.message).toBe('App und Backend sind nicht kompatibel.');
    expect(controller.state.status?.action).toBeUndefined();
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.composerEditingDisabled).toBe(false);
    expect(observe).not.toHaveBeenCalled();
    expect(transport.createSession).toHaveBeenCalledOnce();
    controller.dispose();
  });

  it('retains history and draft after an incompatible submission, including later snapshots', async () => {
    const { transport, controller } = await setup();
    transport.emit(snapshot('completed'));
    await flush();
    const turns = controller.state.turns;
    transport.submitPrompt.mockRejectedValueOnce(new SessionHttpError(405, 'method_not_allowed'));
    const acknowledge = vi.fn();
    await controller.submit('Keep this draft', acknowledge);
    transport.emit(snapshot('completed'));
    await flush();
    expect(controller.state.admission).toBe('rejected');
    expect(controller.state.turns).toEqual(turns);
    expect(controller.state.status?.message).toBe('App und Backend sind nicht kompatibel.');
    expect(controller.state.status?.action).toBeUndefined();
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.composerEditingDisabled).toBe(false);
    expect(acknowledge).not.toHaveBeenCalled();
    await controller.submit('Another prompt', acknowledge);
    expect(transport.submitPrompt).toHaveBeenCalledOnce();
    expect(transport.readSession).not.toHaveBeenCalled();
    controller.dispose();
  });

  it('treats incompatible observer attachment as terminal without offering a retry', async () => {
    const transport = new Transport();
    const observe = vi.spyOn(transport, 'observeSession').mockImplementation(async function* () {
      await Promise.resolve();
      yield* [];
      throw new SessionHttpError(405, 'method_not_allowed');
    });
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    await flush();
    expect(controller.state.status?.message).toBe('App und Backend sind nicht kompatibel.');
    expect(controller.state.status?.action).toBeUndefined();
    expect(controller.state.observation).toBe('lost');
    expect(controller.state.composerDisabled).toBe(true);
    expect(observe).toHaveBeenCalledOnce();
    expect(transport.readSession).not.toHaveBeenCalled();
    controller.dispose();
  });

  it.each(['unknown', 'unknown_configuration', 'agent_unavailable'] as const)(
    'blocks submissions to an unusable session after %s admission failure',
    async (kind) => {
      const { transport, controller } = await setup();
      transport.submitPrompt.mockRejectedValueOnce(new SessionHttpError(404, kind));
      await controller.submit('same', vi.fn());
      transport.emit(snapshot());
      await flush();
      expect(controller.state.admission).toBe('rejected');
      expect(controller.state.composerDisabled).toBe(true);
      expect(controller.state.status?.action?.id).toBe('new-session');
      await controller.submit('same', vi.fn());
      expect(transport.submitPrompt).toHaveBeenCalledOnce();
      controller.dispose();
    },
  );

  it.each(['failed', 'cancelled'] as const)(
    'retains visible %s outcome when observation ends',
    async (status) => {
      const { transport, controller } = await setup();
      transport.emit(snapshot(status));
      transport.end();
      await flush();
      expect(controller.state.status?.message).toContain(
        status === 'failed' ? 'Antwort konnte nicht erstellt' : 'Antwort wurde abgebrochen',
      );
      expect(controller.state.turns[1].content).toMatchObject([{ kind: 'failure' }]);
      controller.dispose();
    },
  );

  it('keeps waiting dots when an artifact is intentionally omitted, then removes them for visible response', async () => {
    const transport = new Transport();
    const controller = new SessionController(transport, vi.fn(), () => null);
    await controller.start();
    transport.emit(snapshot());
    await flush();
    await controller.submit('same', vi.fn());
    const current = snapshot('running');
    const turn = current.history[1];
    if (turn.part_kind !== 'turn') throw new Error('Expected execution group');
    transport.emit({
      ...current,
      history: [
        current.history[0],
        {
          ...turn,
          parts: [
            {
              part_kind: 'artifact',
              artifact: {
                artifact_id: 'a',
                created_at: time,
                run_id: 'run',
                type: 'json',
                content: { title: 'Omitted', payload: null },
              },
            },
          ],
        },
      ],
    });
    await flush();
    expect(controller.state.status?.kind).toBe('loading');
    transport.emit({
      ...current,
      history: [
        current.history[0],
        { ...turn, parts: [{ part_kind: 'text', phase: 'final_answer', content: 'Answer' }] },
      ],
    });
    await flush();
    expect(controller.state.status).toBeNull();
    expect(controller.state.composerDisabled).toBe(true);
    controller.dispose();
  });

  it('offers new-session recovery for a known unavailable observation error while retaining content', async () => {
    const { transport, controller } = await setup();
    transport.emit(snapshot('completed'));
    transport.error('unknown');
    await flush();
    expect(controller.state.turns).toHaveLength(2);
    expect(controller.state.turns[1].status).toBe('completed');
    expect(controller.state.status?.action).toEqual({
      id: 'new-session',
      label: 'Neue Unterhaltung starten',
    });
    expect(controller.state.observation).toBe('lost');
    expect(controller.state.composerDisabled).toBe(true);
    expect(transport.signal?.aborted).toBe(true);
    controller.dispose();
  });

  it('recognizes unavailable observer attachment without retrying observation', async () => {
    const transport = new Transport();
    const observe = vi.spyOn(transport, 'observeSession').mockImplementation(async function* () {
      await Promise.resolve();
      yield* [];
      throw new SessionHttpError(404, 'unknown');
    });
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    await flush();
    expect(controller.state.status?.action?.id).toBe('new-session');
    expect(controller.state.composerDisabled).toBe(true);
    expect(observe).toHaveBeenCalledOnce();
    expect(transport.readSession).not.toHaveBeenCalled();
    controller.dispose();
  });

  it('does not dispatch requests after synchronous disposal from state publication', async () => {
    const transport = new Transport();
    const controller = new SessionController(transport, (state) => {
      if (state.admission === 'pending') controller.dispose();
    });
    await controller.start();
    transport.emit(snapshot());
    await flush();
    const acknowledge = vi.fn();
    await controller.submit('same', acknowledge);
    expect(transport.submitPrompt).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(transport.signal?.aborted).toBe(true);

    const initial = new SessionController(transport, () => initial.dispose());
    await initial.start();
    expect(transport.createSession).toHaveBeenCalledOnce();
  });

  it('disposes observation and ignores late admission and creation without cancelling execution', async () => {
    const { transport, controller } = await setup();
    const admission = deferred<TurnAccepted>();
    transport.submitPrompt.mockReturnValueOnce(admission.promise);
    const acknowledge = vi.fn();
    const pending = controller.submit('same', acknowledge);
    controller.dispose();
    expect(transport.signal?.aborted).toBe(true);
    admission.resolve({ kind: 'accepted' });
    await pending;
    expect(acknowledge).not.toHaveBeenCalled();
    const creation = deferred<SessionCreated>();
    transport.createSession.mockReturnValueOnce(creation.promise);
    const start = controller.start();
    controller.dispose();
    creation.resolve({ session_id: 'late', expires_at: time });
    await start;
    expect(transport.signal?.aborted).toBe(true);
  });
});

describe('session observation reconnection', () => {
  afterEach(() => vi.useRealTimers());

  it.each(['running', 'completed', 'failed', 'cancelled'] as const)(
    'restores the authoritative %s snapshot after a connection ends',
    async (status) => {
      vi.useFakeTimers();
      const transport = new Transport();
      const observe = vi.spyOn(transport, 'observeSession');
      const controller = new SessionController(transport, vi.fn());
      await controller.start();
      transport.emit(snapshot());
      await vi.advanceTimersByTimeAsync(0);
      const acknowledge = vi.fn();
      await controller.submit('same', acknowledge);
      transport.emit(snapshot('running'));
      transport.end();
      await vi.advanceTimersByTimeAsync(0);
      expect(controller.state.observation).toBe('lost');
      expect(controller.state.turns[1].status).toBe('unknown');
      expect(controller.state.composerDisabled).toBe(true);
      transport.emit(snapshot(status));
      await vi.advanceTimersByTimeAsync(999);
      expect(observe).toHaveBeenCalledOnce();
      await vi.advanceTimersByTimeAsync(1);
      expect(observe).toHaveBeenCalledTimes(2);
      expect(controller.state.observation).toBe('connected');
      expect(controller.state.snapshot).toEqual(snapshot(status));
      expect(controller.state.turns[1].status).toBe(status === 'running' ? 'active' : status);
      expect(controller.state.composerDisabled).toBe(status === 'running');
      expect(acknowledge).toHaveBeenCalledOnce();
      expect(transport.submitPrompt).toHaveBeenCalledOnce();
      expect(transport.createSession).toHaveBeenCalledOnce();
      expect(transport.readSession).not.toHaveBeenCalled();
      controller.dispose();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it('recovers observation between turns without clearing uncertain admission', async () => {
    vi.useFakeTimers();
    const transport = new Transport();
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    transport.emit(snapshot('completed'));
    await vi.advanceTimersByTimeAsync(0);
    transport.submitPrompt.mockRejectedValueOnce(new SessionTransportError('network'));
    const acknowledge = vi.fn();
    await controller.submit('Keep this draft', acknowledge);
    transport.end();
    await vi.advanceTimersByTimeAsync(0);
    transport.emit(snapshot('completed'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(controller.state.observation).toBe('connected');
    expect(controller.state.admission).toBe('uncertain');
    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).toContain('angenommen wurde, ist unbekannt');
    expect(acknowledge).not.toHaveBeenCalled();
    controller.dispose();
  });

  it('re-enables submission after reconnecting between completed turns', async () => {
    vi.useFakeTimers();
    const transport = new Transport();
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    transport.emit(snapshot('completed'));
    transport.end();
    await vi.advanceTimersByTimeAsync(0);
    expect(controller.state.composerDisabled).toBe(true);
    transport.emit(snapshot('completed'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status).toBeNull();
    controller.dispose();
  });

  it.each(['network', 'observation_limit', 'observation_overflow', 'internal_error'] as const)(
    'retries %s observation failures with a delay',
    async (reason) => {
      vi.useFakeTimers();
      const transport = new Transport();
      const observe = vi.spyOn(transport, 'observeSession');
      observe.mockImplementationOnce(async function* () {
        await Promise.resolve();
        if (reason === 'network') throw new SessionTransportError('network');
        if (reason === 'observation_limit') throw new SessionHttpError(429, 'observation_limit');
        yield { kind: 'error', reason };
      });
      const controller = new SessionController(transport, vi.fn());
      await controller.start();
      await vi.advanceTimersByTimeAsync(0);
      expect(controller.state.observation).toBe('lost');
      expect(observe).toHaveBeenCalledOnce();
      transport.emit(snapshot());
      await vi.advanceTimersByTimeAsync(1000);
      expect(observe).toHaveBeenCalledTimes(2);
      expect(controller.state.observation).toBe('connected');
      expect(controller.state.composerDisabled).toBe(false);
      controller.dispose();
    },
  );

  it.each([
    new SessionHttpError(405, 'method_not_allowed'),
    new SessionHttpError(404, 'unknown'),
    new SessionHttpError(404, 'unknown_configuration'),
    new SessionHttpError(503, 'agent_unavailable'),
    new SessionTransportError('invalid_response'),
  ])('does not reconnect after a non-transient failure: %s', async (error) => {
    vi.useFakeTimers();
    const transport = new Transport();
    const observe = vi.spyOn(transport, 'observeSession').mockImplementation(async function* () {
      await Promise.resolve();
      yield* [];
      throw error;
    });
    const controller = new SessionController(transport, vi.fn());
    await controller.start();
    await vi.advanceTimersByTimeAsync(5000);
    expect(observe).toHaveBeenCalledOnce();
    expect(controller.state.observation).toBe('lost');
    expect(controller.state.composerDisabled).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    controller.dispose();
  });

  it('spaces repeated failures and cancels pending reconnection on disposal', async () => {
    vi.useFakeTimers();
    const transport = new Transport();
    const observe = vi.spyOn(transport, 'observeSession').mockImplementation(async function* () {
      await Promise.resolve();
      yield* [];
      throw new SessionTransportError('network');
    });
    const publish = vi.fn();
    const controller = new SessionController(transport, publish);
    await controller.start();
    await vi.advanceTimersByTimeAsync(3000);
    expect(observe).toHaveBeenCalledTimes(4);
    controller.dispose();
    const publications = publish.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(observe).toHaveBeenCalledTimes(4);
    expect(publish).toHaveBeenCalledTimes(publications);
    expect(vi.getTimerCount()).toBe(0);
  });
});
