import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConversationNetworkError, HttpConversationTransport } from './conversation-api';
import type { StreamEvent } from '../generated/types.gen';

describe('fetch SSE observation', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('delivers validated events before EOF across arbitrary UTF-8/frame boundaries without reconnect', async () => {
    let push!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = controller;
      },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    const events = new HttpConversationTransport('/ai/api/v1/', 'demo', 'test:user').observeTurn(
      's',
      't',
      new AbortController().signal,
    );
    const iterator = events[Symbol.asyncIterator]();
    const event: StreamEvent = {
      kind: 'upsert',
      turn_id: 't',
      identity: 'm',
      order: 1,
      sequence: 2,
      item: { kind: 'message', turn_id: 't', id: 'm', role: 'assistant', text: 'Gr\u00fc\u00dfe' },
    };
    const bytes = new TextEncoder().encode(
      `: heartbeat\r\n\r\ndata: ${JSON.stringify(event)}\r\n\r\n`,
    );
    const pending = iterator.next();
    for (const byte of bytes) push.enqueue(Uint8Array.of(byte));
    expect(await pending).toEqual({ done: false, value: event });
    push.close();
    expect(await iterator.next()).toMatchObject({ done: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/ai/api/v1/agents/demo/sessions/s/turns/t/events');
  });
  it.each([
    '{"kind":"future"}',
    '{bad json}',
    '{"kind":"terminal","turn_id":"t","sequence":1,"outcome":"success"}',
  ])('rejects malformed event %s without replacement requests', async (data) => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(`data: ${data}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const events = new HttpConversationTransport('/api/v1', 'demo', 'test:user').observeTurn(
      's',
      't',
      new AbortController().signal,
    );
    const iterator = events[Symbol.asyncIterator]();
    await expect(iterator.next()).rejects.toBeInstanceOf(ConversationNetworkError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it('accepts legitimate retained snapshots larger than four MiB delivered in chunks', async () => {
    const timeline = Array.from({ length: 300 }, (_, index) => ({
      kind: 'intermediate' as const,
      turn_id: 't',
      id: `m-${index}`,
      text: 'x'.repeat(16000),
    }));
    const event: StreamEvent = {
      kind: 'snapshot',
      turn_id: 't',
      snapshot: {
        session_id: 's',
        expires_at: '2026-10-04T20:00:00Z',
        sequence: 300,
        turns: [
          {
            turn_id: 't',
            user_message_id: 'user',
            status: 'in_progress',
            timeline: [
              { kind: 'message', role: 'user', id: 'user', text: 'Hello', turn_id: 't' },
              ...timeline,
            ],
          },
        ],
      },
    };
    const bytes = new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`);
    expect(bytes.length).toBeGreaterThan(4 * 1024 * 1024);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let start = 0; start < bytes.length; start += 16384)
          controller.enqueue(bytes.slice(start, start + 16384));
        controller.close();
      },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    const events = new HttpConversationTransport('/api/v1', 'demo', 'test:user').observeTurn(
      's',
      't',
      new AbortController().signal,
    );
    const iterator = events[Symbol.asyncIterator]();
    expect((await iterator.next()).value).toEqual(event);
    expect(await iterator.next()).toMatchObject({ done: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
