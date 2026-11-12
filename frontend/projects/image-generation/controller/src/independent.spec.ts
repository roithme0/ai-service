import { describe, expect, it, vi } from 'vitest';
import { HttpImageGenerationTransport } from './transport';
import { zImageEvent } from './generated/zod.gen';
import { ImageGenerationController, InvalidStateError } from './controller';

const inputUrl = (input: RequestInfo | URL): string =>
  typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;

const id = '6e97d91c-7b11-4e3a-9607-d5a560205a23';
const completed = {
  generation_id: id,
  status: 'completed' as const,
  created_at: '2026-11-08T00:00:00Z',
  completed_at: '2026-11-08T00:00:01Z',
  configured_model: 'gpt-image-test',
  provider_model: null,
  estimated_cost_usd: null,
  content: {
    media_type: 'image/png' as const,
    size_bytes: 3,
    url: 'https://untrusted.example/image',
  },
};

describe('independent consumer contract', () => {
  it('recovers uncertain admission with exact text and key, and uses canonical owned content', async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    const fetcher: typeof fetch = async (input, init) => {
      await Promise.resolve();
      calls.push({ url: inputUrl(input), init: init ?? {} });
      if (calls.length === 1) return new Response('proxy failure', { status: 503 });
      if (calls.length === 2) return Response.json(completed, { status: 200 });
      return new Response(new Uint8Array([1, 2, 3]), { headers: { 'content-type': 'image/png' } });
    };
    const transport = new HttpImageGenerationTransport(
      'https://api.example/api/v1',
      'issuer:subject',
      fetcher,
    );
    const publish = vi.fn();
    const controller = new ImageGenerationController(transport, publish);
    await controller.submit('  original text  ');
    expect(controller.state.admission).toBe('uncertain');
    await expect(controller.submit('different')).rejects.toBeInstanceOf(InvalidStateError);
    await controller.recoverSubmission();
    expect(controller.state.snapshot).toEqual(completed);
    const content = await controller.loadContent();
    expect(content.filename).toBe(`${id}.png`);
    expect(content.blob.size).toBe(3);
    expect(calls.map((call) => call.url)).toEqual([
      'https://api.example/api/v1/image-generations',
      'https://api.example/api/v1/image-generations',
      `https://api.example/api/v1/image-generations/${id}/content`,
    ]);
    const first = new Headers(calls[0].init.headers);
    const second = new Headers(calls[1].init.headers);
    expect(first.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(second.get('Idempotency-Key')).toBe(first.get('Idempotency-Key'));
    expect(calls[1].init.body).toBe(calls[0].init.body);
    for (const call of calls)
      expect(new Headers(call.init.headers).get('X-Application-User')).toBe('issuer:subject');
    controller.dispose();
  });
});

it('parses chunked UTF-8, CRLF, comments and multiline data through terminal and cancels reader', async () => {
  let cancelled = false;
  const event = JSON.stringify({
    kind: 'snapshot',
    snapshot: { ...completed, configured_model: 'modï¿½le' },
  });
  const split = event.indexOf(',"snapshot"');
  const bytes = new TextEncoder().encode(
    `: keepalive\r\ndata: ${event.slice(0, split + 1)}\r\ndata: ${event.slice(split + 1)}\r\n\r\n`,
  );
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    },
    cancel() {
      cancelled = true;
    },
  });
  const fetcher: typeof fetch = () =>
    Promise.resolve(new Response(stream, { headers: { 'content-type': 'text/event-stream' } }));
  const transport = new HttpImageGenerationTransport(
    'https://api.example/api/v1',
    'issuer:subject',
    fetcher,
  );
  const events = [];
  for await (const item of transport.observe(id, new AbortController().signal)) events.push(item);
  expect(events).toEqual([
    { kind: 'snapshot', snapshot: { ...completed, configured_model: 'modï¿½le' } },
  ]);
  expect(cancelled).toBe(true);
});

it('rejects truncated event and wrong generation identity', async () => {
  for (const body of [
    'data: {"kind":"snapshot"}',
    `data: ${JSON.stringify({ kind: 'snapshot', snapshot: { ...completed, generation_id: '76c024b0-9948-447f-a3f4-08b43969ee48' } })}\n\n`,
  ]) {
    const fetcher: typeof fetch = () =>
      Promise.resolve(new Response(body, { headers: { 'content-type': 'text/event-stream' } }));
    const transport = new HttpImageGenerationTransport(
      'https://api.example/api/v1',
      'issuer:subject',
      fetcher,
    );
    const consume = async () => {
      for await (const event of transport.observe(id, new AbortController().signal))
        expect(event).toBeDefined();
    };
    await expect(consume()).rejects.toThrow();
  }
});

it('treats documented unavailable as rejection and malformed 503 as uncertain', async () => {
  for (const [body, expected] of [
    [{ kind: 'image_generation_unavailable', detail: 'Unavailable' }, 'rejected'],
    [{ kind: 'image_generation_unavailable' }, 'uncertain'],
  ] as const) {
    const fetcher: typeof fetch = () => Promise.resolve(Response.json(body, { status: 503 }));
    const controller = new ImageGenerationController(
      new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
      () => {},
    );
    await controller.submit('prompt');
    expect(controller.state.admission).toBe(expected);
    controller.dispose();
  }
});

it('keeps completion after invalid content and allows a retry', async () => {
  let count = 0;
  const fetcher: typeof fetch = async () => {
    await Promise.resolve();
    count++;
    if (count === 1) return Response.json(completed);
    if (count === 2) return new Response('', { headers: { 'content-type': 'image/png' } });
    return new Response('png', { headers: { 'content-type': 'image/png' } });
  };
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    () => {},
  );
  await controller.submit('prompt');
  await expect(controller.loadContent()).rejects.toThrow();
  expect(controller.state.snapshot).toEqual(completed);
  expect(controller.state.content).toBe('error');
  expect((await controller.loadContent()).blob.size).toBe(3);
  controller.dispose();
});

it('distinguishes EOF from generation failure and reconnects with GET only', async () => {
  const running = { ...completed, status: 'running' as const, completed_at: null };
  const calls: string[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    await Promise.resolve();
    const url = inputUrl(input);
    calls.push(`${init?.method ?? 'GET'} ${url}`);
    if (init?.method === 'POST') return Response.json(running, { status: 202 });
    if (url.endsWith('/events'))
      return new Response('', { headers: { 'content-type': 'text/event-stream' } });
    return Response.json(completed);
  };
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    () => {},
  );
  await controller.submit('prompt');
  await vi.waitFor(() => expect(controller.state.observation).toBe('lost'));
  expect(controller.state.snapshot?.status).toBe('running');
  controller.reconnect();
  await vi.waitFor(() => expect(controller.state.observation).toBe('lost'));
  await controller.readStatus();
  expect(controller.state.snapshot?.status).toBe('completed');
  expect(calls.filter((call) => call.startsWith('POST '))).toHaveLength(1);
  expect(calls.filter((call) => call.endsWith(`${id}/events`))).toHaveLength(2);
  controller.dispose();
});

it('suppresses a late admission result after disposal', async () => {
  let finish: ((response: Response) => void) | undefined;
  const fetcher: typeof fetch = async () =>
    new Promise<Response>((resolve) => {
      finish = resolve;
    });
  const publish = vi.fn();
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    publish,
  );
  const pending = controller.submit('prompt');
  controller.dispose();
  const publications = publish.mock.calls.length;
  expect(finish).toBeDefined();
  finish?.(Response.json(completed));
  await pending;
  expect(publish).toHaveBeenCalledTimes(publications);
  await expect(controller.submit('again')).rejects.toBeInstanceOf(InvalidStateError);
});

it('accepts both event variants and every snapshot status', async () => {
  const base = {
    generation_id: id,
    created_at: completed.created_at,
    configured_model: completed.configured_model,
    provider_model: null,
    estimated_cost_usd: null,
    completed_at: completed.completed_at,
  };
  const running = { ...base, status: 'running', completed_at: null };
  const failed = {
    ...base,
    status: 'failed',
    error: { kind: 'image_generation_provider_failed', detail: 'Provider failed' },
  };
  const cases = [
    [
      { kind: 'snapshot', snapshot: running },
      { kind: 'error', reason: 'internal_error' },
    ],
    [{ kind: 'snapshot', snapshot: completed }],
    [{ kind: 'snapshot', snapshot: failed }],
  ];
  for (const expected of cases) {
    const body = expected.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
    const fetcher: typeof fetch = () =>
      Promise.resolve(new Response(body, { headers: { 'content-type': 'text/event-stream' } }));
    const transport = new HttpImageGenerationTransport(
      'https://api.example/api/v1',
      'issuer:subject',
      fetcher,
    );
    const actual = [];
    for await (const event of transport.observe(id, new AbortController().signal))
      actual.push(event);
    expect(actual).toEqual(expected);
  }
});

it('generated event schema requires discriminators and error reason', () => {
  expect(zImageEvent.safeParse({ kind: 'snapshot', snapshot: completed }).success).toBe(true);
  expect(zImageEvent.safeParse({ kind: 'error', reason: 'internal_error' }).success).toBe(true);
  expect(zImageEvent.safeParse({ snapshot: completed }).success).toBe(false);
  expect(zImageEvent.safeParse({ kind: 'error' }).success).toBe(false);
});

it.each(['submitting', 'accepted', 'observing', 'loading'] as const)(
  'does not start work after publisher disposes during %s',
  async (phase) => {
    const calls: string[] = [];
    const running = { ...completed, status: 'running', completed_at: null };
    const fetcher: typeof fetch = async (input) => {
      await Promise.resolve();
      calls.push(inputUrl(input));
      return Response.json(phase === 'loading' ? completed : running, { status: 202 });
    };
    const controller = new ImageGenerationController(
      new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
      (state) => {
        if (state.admission === phase || state.observation === phase || state.content === phase)
          controller.dispose();
      },
    );
    await controller.submit('prompt');
    if (phase === 'loading')
      await expect(controller.loadContent()).rejects.toBeInstanceOf(InvalidStateError);
    await Promise.resolve();
    expect(calls).toHaveLength(phase === 'submitting' ? 0 : 1);
  },
);

it('exposes typed transport errors for network, invalid schema, and HTTP failures', async () => {
  for (const failure of ['network', 'schema', 'http'] as const) {
    const fetcher: typeof fetch = async () => {
      await Promise.resolve();
      if (failure === 'network') throw new TypeError('network');
      if (failure === 'http') return new Response('missing', { status: 404 });
      return Response.json({ invalid: true });
    };
    const transport = new HttpImageGenerationTransport(
      'https://api.example/api/v1',
      'issuer:subject',
      fetcher,
    );
    const signal = new AbortController().signal;
    await expect(transport.read(id, signal)).rejects.toMatchObject({ category: 'unavailable' });
    await expect(transport.content(id, signal)).rejects.toMatchObject({ category: 'content' });
    const observe = async () => {
      for await (const event of transport.observe(id, signal)) expect(event).toBeDefined();
    };
    await expect(observe()).rejects.toMatchObject({ category: 'observation' });
  }
});

it('uses a fresh idempotency key for a new explicit run after completion', async () => {
  const keys: Array<string | null> = [];
  const fetcher: typeof fetch = async (_input, init) => {
    await Promise.resolve();
    keys.push(new Headers(init?.headers).get('Idempotency-Key'));
    return Response.json(completed);
  };
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    () => {},
  );
  await controller.submit('first');
  await controller.submit('second');
  expect(keys).toHaveLength(2);
  expect(keys[0]).not.toBe(keys[1]);
  controller.dispose();
});

it('does not regress a terminal snapshot when an older GET resolves later', async () => {
  const running = { ...completed, status: 'running', completed_at: null };
  let completeStream: ((value: Response) => void) | undefined;
  let completeRead: ((value: Response) => void) | undefined;
  const fetcher: typeof fetch = (input, init) => {
    if (init?.method === 'POST') return Promise.resolve(Response.json(running, { status: 202 }));
    if (inputUrl(input).endsWith('/events'))
      return new Promise<Response>((resolve) => {
        completeStream = resolve;
      });
    return new Promise<Response>((resolve) => {
      completeRead = resolve;
    });
  };
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    () => {},
  );
  await controller.submit('prompt');
  const read = controller.readStatus();
  completeStream?.(
    new Response(`data: ${JSON.stringify({ kind: 'snapshot', snapshot: completed })}\n\n`, {
      headers: { 'content-type': 'text/event-stream' },
    }),
  );
  await vi.waitFor(() => expect(controller.state.snapshot?.status).toBe('completed'));
  completeRead?.(Response.json(running));
  await expect(read).rejects.toThrow();
  expect(controller.state.snapshot).toEqual(completed);
  controller.dispose();
});

it('ignores a late observation from the previous generation after replacement', async () => {
  const nextId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const running = { ...completed, status: 'running', completed_at: null };
  let finishOld: ((value: Response) => void) | undefined;
  let posts = 0;
  const fetcher: typeof fetch = (input, init) => {
    if (init?.method === 'POST') {
      posts++;
      return Promise.resolve(
        Response.json(posts === 1 ? running : { ...completed, generation_id: nextId }),
      );
    }
    if (inputUrl(input).endsWith('/events'))
      return new Promise<Response>((resolve) => {
        finishOld = resolve;
      });
    return Promise.resolve(Response.json(completed));
  };
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('https://api.example/api/v1', 'issuer:subject', fetcher),
    () => {},
  );
  await controller.submit('first');
  await controller.readStatus();
  await controller.submit('second');
  finishOld?.(
    new Response(`data: ${JSON.stringify({ kind: 'snapshot', snapshot: completed })}\n\n`, {
      headers: { 'content-type': 'text/event-stream' },
    }),
  );
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  expect(controller.state.snapshot?.generation_id).toBe(nextId);
  expect(controller.state.observation).toBe('idle');
  controller.dispose();
});

it('preserves a local abort while reading the submission response body', async () => {
  const abort = new AbortController();
  const reason = new DOMException('Stopped locally', 'AbortError');
  const response = Response.json(completed);
  let rejectBody: ((reason: DOMException) => void) | undefined;
  response.json = () =>
    new Promise<never>((_resolve, reject: (reason: DOMException) => void) => {
      rejectBody = reject;
    });
  const fetcher: typeof fetch = () => Promise.resolve(response);
  const transport = new HttpImageGenerationTransport(
    'https://api.example/api/v1',
    'issuer:subject',
    fetcher,
  );
  const pending = transport.submit('prompt', crypto.randomUUID(), abort.signal);
  await vi.waitFor(() => expect(rejectBody).toBeDefined());
  abort.abort(reason);
  rejectBody?.(reason);
  await expect(pending).rejects.toBe(reason);
});
