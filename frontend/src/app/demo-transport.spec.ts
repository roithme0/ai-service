import { ConversationApiError } from '@roithme0/chat-ui/conversation';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoTransport } from './demo-transport';

describe('DemoTransport', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  it('counts successful terminal events, preserves the scripted failure, and resets with a fresh session', async () => {
    vi.useFakeTimers(); let turnCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith('/sessions')) return Response.json({ session_id: 'demo-1', expires_at: '2026-10-04T20:00:00Z' });
      if (url.endsWith('/messages')) return Response.json({ role: 'user', text: 'Next', turn_id: null });
      if (url.endsWith('/turns')) { turnCount += 1; return Response.json({ kind: 'accepted', turn_id: `turn-${turnCount}` }); }
      if (url.endsWith('/events')) return new Response(`data: ${JSON.stringify({ kind: 'terminal', turn_id: `turn-${turnCount}`, sequence: turnCount, outcome: turnCount === 3 ? 'generation_failed' : 'completed' })}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } });
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock); const transport = new DemoTransport();
    const creation = transport.createSession(); await vi.advanceTimersByTimeAsync(1500); const { session_id: sessionId } = await creation;
    for (let turn = 1; turn <= 4; turn += 1) {
      const append = transport.appendMessage(sessionId, 'Next'); await vi.advanceTimersByTimeAsync(1500); await append;
      const start = await transport.generateTurn(sessionId);
      for await (const event of transport.observeTurn(sessionId, start.turn_id, new AbortController().signal)) expect(event.kind).toBe('terminal');
    }
    const rejected = expect(transport.appendMessage(sessionId, 'After completion')).rejects.toEqual(new ConversationApiError(405, 'method_not_allowed'));
    await vi.advanceTimersByTimeAsync(1500); await rejected;
    const fresh = transport.createSession(); await vi.advanceTimersByTimeAsync(1500); await fresh;
    const append = transport.appendMessage(sessionId, 'Fresh'); await vi.advanceTimersByTimeAsync(1500); await expect(append).resolves.toMatchObject({ role: 'user' });
    expect(fetchMock).toHaveBeenCalledTimes(15);
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).get('X-Application-User')).toBe('demo:default');
    }
  });
});
