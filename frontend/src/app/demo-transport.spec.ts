import { ConversationApiError } from '@roithme0/chat-ui/conversation';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoTransport } from './demo-transport';

describe('DemoTransport', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('simulates a method mismatch only after the scripted completion turn', async () => {
    vi.useFakeTimers();
    let turnCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith('/sessions')) {
        return Response.json({ session_id: 'demo-1', expires_at: '2026-09-29T12:00:00Z' });
      }
      if (url.endsWith('/messages')) {
        return Response.json({ role: 'user', text: 'Next', turn_id: null });
      }
      if (url.endsWith('/turns')) {
        turnCount += 1;
        if (turnCount === 3) {
          return Response.json(
            { detail: 'Turn generation failed', kind: 'generation_failed', turn_id: 'turn-3' },
            { status: 502 },
          );
        }
        return Response.json({
          kind: 'completed', turn_id: `turn-${turnCount}`,
          message: { role: 'assistant', text: 'Scripted reply', turn_id: `turn-${turnCount}` },
          artifacts: [],
        });
      }
      throw new Error(`Unexpected demo request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);
    const transport = new DemoTransport();

    const creation = transport.createSession();
    await vi.advanceTimersByTimeAsync(1500);
    const { session_id: sessionId } = await creation;
    for (let turn = 1; turn <= 4; turn += 1) {
      const append = transport.appendMessage(sessionId, 'Next');
      await vi.advanceTimersByTimeAsync(1500);
      await append;
      if (turn === 3) {
        await expect(transport.generateTurn(sessionId)).rejects.toEqual(
          new ConversationApiError(502, 'generation_failed'),
        );
      } else {
        await expect(transport.generateTurn(sessionId)).resolves.toMatchObject({ kind: 'completed' });
      }
    }

    const failure = expect(transport.appendMessage(sessionId, 'After completion')).rejects.toEqual(
      new ConversationApiError(405, 'method_not_allowed'),
    );
    await vi.advanceTimersByTimeAsync(1500);
    await failure;
    expect(fetchMock).toHaveBeenCalledTimes(9);
  });
});
