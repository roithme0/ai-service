import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpSessionTransport, SessionHttpError, SessionTransportError } from './session-transport';
import type { SessionEvent, PresentedSession } from '../generated/types.gen';

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

const expires = '2026-10-21T12:00:00Z';
const snapshot: PresentedSession = {
  error: null,
  usage: {
    ...EMPTY_USAGE,
    input_tokens: 100,
    output_tokens: 20,
    total_tokens: 120,
    requests: 1,
    estimated_cost_usd: '0.01234567890123456789',
  },
  session_id: 's/1',
  expires_at: expires,
  history: [
    { part_kind: 'user-prompt', content: ['First', 'Second'] },
    {
      part_kind: 'turn',
      usage: EMPTY_USAGE,
      lifecycle: { run_id: null, status: 'running', started_at: expires, finished_at: null },
      parts: [],
    },
    {
      part_kind: 'turn',
      usage: { ...EMPTY_USAGE, estimated_cost_usd: '0' },
      lifecycle: {
        run_id: 'run-1',
        status: 'completed',
        started_at: expires,
        finished_at: expires,
      },
      parts: [
        { part_kind: 'text', content: 'Hello ä', phase: 'commentary' },
        {
          part_kind: 'tool-call',
          tool_name: 'present_artifact',
          tool_call_id: 'call-1',
          status: 'success',
        },
        {
          part_kind: 'artifact',
          artifact: {
            artifact_id: 'artifact-1',
            created_at: expires,
            run_id: 'run-1',
            type: 'json',
            content: {
              title: 'Result',
              payload: { value: [1, true, null] },
              metadata: { source: 'test' },
            },
          },
        },
        {
          part_kind: 'builtin-tool-call',
          tool_name: 'web_search',
          tool_call_id: 'call-2',
          status: 'interrupted',
        },
        { part_kind: 'text', content: 'Done', phase: 'final_answer' },
      ],
    },
  ],
};
const snapshotEvent: SessionEvent = { kind: 'snapshot', snapshot };

function transport(): HttpSessionTransport {
  return new HttpSessionTransport('/ai/api/v1///', 'new/agent', 'test:alice');
}

function events(signal = new AbortController().signal): AsyncIterable<SessionEvent> {
  return transport().observeSession('s/1', signal);
}

function stream(body: BodyInit): Response {
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } });
}

function frame(event: unknown): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

async function collect(source: AsyncIterable<SessionEvent>): Promise<SessionEvent[]> {
  const result: SessionEvent[] = [];
  for await (const event of source) result.push(event);
  return result;
}

describe('HttpSessionTransport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    'test:alice',
    `${encodeURIComponent('https://idp.example/realms/cooks')}:${encodeURIComponent("cook:ä !'()*%")}`,
  ])('preserves owner assertion %s across create, read, submit and observe', async (identity) => {
    const sessionTransport = new HttpSessionTransport('/ai/api/v1///', 'new/agent', identity);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ session_id: 's/1', expires_at: expires }, { status: 201 }),
      )
      .mockResolvedValueOnce(Response.json(snapshot))
      .mockResolvedValueOnce(Response.json({ kind: 'accepted' }, { status: 202 }))
      .mockResolvedValueOnce(stream(frame(snapshotEvent)));
    vi.stubGlobal('fetch', fetchMock);
    const initialization = {
      initial_context: { recipe: { id: 1 } },
      artifact_capabilities: [
        { type: 'json', description: 'JSON', payloadSchema: { type: 'object' } },
      ],
    };
    await expect(sessionTransport.createSession(initialization)).resolves.toEqual({
      session_id: 's/1',
      expires_at: expires,
    });
    await expect(sessionTransport.readSession('s/1')).resolves.toEqual(snapshot);
    await expect(sessionTransport.submitPrompt('s/1', '  Hello  ')).resolves.toEqual({
      kind: 'accepted',
    });
    await expect(
      collect(sessionTransport.observeSession('s/1', new AbortController().signal)),
    ).resolves.toEqual([snapshotEvent]);
    const base = '/ai/api/v1/agents/new%2Fagent/sessions';
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      base,
      `${base}/s%2F1`,
      `${base}/s%2F1/turns`,
      `${base}/s%2F1/events`,
    ]);
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual(initialization);
    expect(fetchMock.mock.calls[2][1]?.body).toBe(JSON.stringify({ prompt: '  Hello  ' }));
    for (const [, options] of fetchMock.mock.calls) {
      expect(new Headers(options?.headers).get('X-Application-User')).toBe(identity);
    }
  });

  it.each([
    [400, 'invalid_input'],
    [404, 'unknown'],
    [404, 'unknown_configuration'],
    [409, 'busy'],
    [429, 'observation_limit'],
    [503, 'agent_unavailable'],
  ] as const)('preserves HTTP %i / %s without retrying', async (status, kind) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ kind }, { status }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toMatchObject({ status, kind });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('recognizes FastAPI validation failures without exposing validation input', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(
        Response.json(
          {
            detail: [
              { loc: ['body', 'prompt'], msg: 'Invalid', type: 'value_error', input: 'private' },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    await expect(transport().submitPrompt('s/1', '')).rejects.toEqual(
      new SessionHttpError(422, 'validation_error'),
    );
  });

  it.each(['{"detail":"Method Not Allowed"}', '<html>Method Not Allowed</html>', ''])(
    'classifies HTTP 405 independently of its response body %j across all endpoints',
    async (body) => {
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockImplementation(() => Promise.resolve(new Response(body, { status: 405 })));
      vi.stubGlobal('fetch', fetchMock);
      const error = new SessionHttpError(405, 'method_not_allowed');
      await expect(transport().createSession()).rejects.toEqual(error);
      await expect(transport().readSession('s/1')).rejects.toEqual(error);
      await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toEqual(error);
      await expect(collect(events())).rejects.toEqual(error);
      expect(fetchMock).toHaveBeenCalledTimes(4);
    },
  );

  it('distinguishes network failure from invalid JSON and unexpected success status', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockRejectedValueOnce(new TypeError('offline'))
        .mockResolvedValueOnce(new Response('not JSON'))
        .mockResolvedValueOnce(Response.json({ kind: 'accepted' })),
    );
    await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toMatchObject({
      reason: 'network',
    });
    await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toMatchObject({
      reason: 'invalid_response',
    });
    await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toMatchObject({
      reason: 'invalid_response',
    });
  });

  it.each([{}, { kind: 'not_a_real_error' }, { detail: 'unexpected' }])(
    'rejects malformed HTTP error envelopes %j',
    async (body) => {
      vi.stubGlobal(
        'fetch',
        vi.fn<typeof fetch>().mockResolvedValue(Response.json(body, { status: 404 })),
      );
      await expect(transport().readSession('s/1')).rejects.toBeInstanceOf(SessionTransportError);
    },
  );

  it('rejects non-JSON initialization before making a request', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
    await expect(
      transport().createSession({ initial_context: { number: Infinity } }),
    ).rejects.toBeInstanceOf(SessionTransportError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires an explicit admission acknowledgement rather than treating an empty object as accepted', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(Response.json({}, { status: 202 })),
    );
    await expect(transport().submitPrompt('s/1', 'Hello')).rejects.toMatchObject({
      reason: 'invalid_response',
    });
  });

  it('rejects another session in reads and event frames', async () => {
    const wrong = { ...snapshot, session_id: 'someone-else' };
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json(wrong))
        .mockResolvedValueOnce(stream(frame({ kind: 'snapshot', snapshot: wrong }))),
    );
    await expect(transport().readSession('s/1')).rejects.toBeInstanceOf(SessionTransportError);
    await expect(collect(events())).rejects.toBeInstanceOf(SessionTransportError);
  });
});

describe('session observation', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('parses large chunked snapshots with split separators and subsequent frames', async () => {
    const largeSnapshot: SessionEvent = {
      kind: 'snapshot',
      snapshot: {
        ...snapshot,
        history: [{ part_kind: 'user-prompt', content: ['x'.repeat(4 * 1024 * 1024)] }],
      },
    };
    const encoder = new TextEncoder();
    const data = encoder.encode(frame(largeSnapshot));
    let offset = 0;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (offset < data.length - 1) {
          const end = Math.min(offset + 1024, data.length - 1);
          controller.enqueue(data.subarray(offset, end));
          offset = end;
        } else {
          controller.enqueue(encoder.encode(`\n${frame(snapshotEvent)}${frame(snapshotEvent)}`));
          controller.close();
        }
      },
    });
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(stream(body)));

    await expect(collect(events())).resolves.toEqual([largeSnapshot, snapshotEvent, snapshotEvent]);
    expect(body.locked).toBe(false);
  });

  it('delivers snapshots before EOF across every UTF-8 and CRLF boundary, and keeps observing settled turns', async () => {
    let push!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = controller;
      },
    });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(stream(body));
    vi.stubGlobal('fetch', fetchMock);
    const iterator = events()[Symbol.asyncIterator]();
    const first = iterator.next();
    const encoded = new TextEncoder().encode(
      `: comment\r\n\r\ndata: ${JSON.stringify(snapshotEvent)}\r\n\r\n`,
    );
    for (const byte of encoded) push.enqueue(new Uint8Array([byte]));
    expect(await first).toEqual({ done: false, value: snapshotEvent });
    const followUp = { kind: 'snapshot', snapshot: { ...snapshot, history: [] } };
    const second = iterator.next();
    push.enqueue(new TextEncoder().encode(frame(followUp)));
    expect(await second).toEqual({ done: false, value: followUp });
    push.close();
    expect((await iterator.next()).done).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(body.locked).toBe(false);
  });

  it.each(['unknown', 'observation_overflow', 'internal_error'] as const)(
    'delivers %s as an observation error and ends without reconnecting',
    async (reason) => {
      const error: SessionEvent = { kind: 'error', reason };
      const cancel = vi.fn<UnderlyingSourceCancelCallback>();
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(frame(snapshotEvent) + frame(error) + frame(snapshotEvent)),
          );
        },
        cancel,
      });
      const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(stream(body));
      vi.stubGlobal('fetch', fetchMock);
      await expect(collect(events())).resolves.toEqual([snapshotEvent, error]);
      expect(cancel).toHaveBeenCalledOnce();
      expect(body.locked).toBe(false);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it.each([
    'data: {broken}\n\n',
    frame({ snapshot }),
    frame({ kind: 'snapshot', snapshot: { ...snapshot, usage: undefined } }),
    frame({
      kind: 'snapshot',
      snapshot: { ...snapshot, usage: { ...EMPTY_USAGE, estimated_cost_usd: 0.01 } },
    }),
    frame({ kind: 'surprise' }),
    frame({ kind: 'error', reason: 'surprise' }),
    frame({ kind: 'snapshot', snapshot: { ...snapshot, history: [{ content: 'missing kind' }] } }),
    frame({
      kind: 'snapshot',
      snapshot: {
        ...snapshot,
        history: [
          {
            part_kind: 'turn',
            usage: EMPTY_USAGE,
            lifecycle: { run_id: null, status: 'running', started_at: expires, finished_at: null },
            parts: [
              { part_kind: 'tool-call', tool_name: 'x', tool_call_id: 'c', status: 'made_up' },
            ],
          },
        ],
      },
    }),
    frame(snapshotEvent).trimEnd(),
  ])('rejects malformed or truncated frames %#', async (body) => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(stream(body)));
    await expect(collect(events())).rejects.toMatchObject({ reason: 'invalid_response' });
  });

  it.each(['\n', '\r', '\r\n'])(
    'handles multiline data with byte-split %j line endings',
    async (separator) => {
      const data = JSON.stringify(snapshotEvent, null, 2)
        .split('\n')
        .map((line) => `data: ${line}`)
        .join(separator);
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const byte of new TextEncoder().encode(`${data}${separator}${separator}`)) {
            controller.enqueue(new Uint8Array([byte]));
          }
          controller.close();
        },
      });
      vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(stream(body)));
      await expect(collect(events())).resolves.toEqual([snapshotEvent]);
    },
  );

  it('reports pre-header capacity failure as HTTP error', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json({ kind: 'observation_limit' }, { status: 429 })),
    );
    await expect(collect(events())).rejects.toMatchObject({
      status: 429,
      kind: 'observation_limit',
    });
  });

  it('rejects non-SSE content and invalid UTF-8', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(Response.json(snapshotEvent))
        .mockResolvedValueOnce(stream(new Uint8Array([0xff]))),
    );
    await expect(collect(events())).rejects.toMatchObject({ reason: 'invalid_response' });
    await expect(collect(events())).rejects.toMatchObject({ reason: 'invalid_response' });
  });

  it('releases the reader when a consumer stops early', async () => {
    const cancel = vi.fn<UnderlyingSourceCancelCallback>();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame(snapshotEvent)));
      },
      cancel,
    });
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(stream(body)));
    for await (const event of events()) {
      expect(event).toEqual(snapshotEvent);
      break;
    }
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
  });

  it.each(['data: {broken}\n\n', frame({ kind: 'unexpected' })])(
    'releases an open stream when event parsing fails %#',
    async (data) => {
      const cancel = vi.fn<UnderlyingSourceCancelCallback>();
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(data));
        },
        cancel,
      });
      vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(stream(body)));
      await expect(collect(events())).rejects.toMatchObject({ reason: 'invalid_response' });
      expect(cancel).toHaveBeenCalledOnce();
      expect(body.locked).toBe(false);
    },
  );

  it('propagates abort and releases a pending reader without making an execution request', async () => {
    const abort = new AbortController();
    let push!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = controller;
      },
    });
    const fetchMock = vi.fn<typeof fetch>().mockImplementation((_url, options) => {
      options?.signal?.addEventListener('abort', () => push.error(abort.signal.reason));
      return Promise.resolve(stream(body));
    });
    vi.stubGlobal('fetch', fetchMock);
    const consuming = collect(events(abort.signal));
    await vi.waitFor(() => expect(body.locked).toBe(true));
    abort.abort();
    await expect(consuming).rejects.toBe(abort.signal.reason);
    expect(body.locked).toBe(false);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('preserves network failure during fetch and while reading', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn<typeof fetch>()
        .mockRejectedValueOnce(new TypeError('offline'))
        .mockResolvedValueOnce(
          stream(
            new ReadableStream<Uint8Array>({
              start(controller) {
                controller.error(new TypeError('disconnected'));
              },
            }),
          ),
        ),
    );
    await expect(collect(events())).rejects.toMatchObject({ reason: 'network' });
    await expect(collect(events())).rejects.toMatchObject({ reason: 'network' });
  });
});
