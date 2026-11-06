import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpTranscriber, TranscriptionError } from './http-transcriber';

const recording = {
  blob: new Blob(['audio'], { type: 'audio/webm' }),
  mimeType: 'audio/webm',
  durationMs: 100,
  stopReason: 'manual' as const,
};
afterEach(() => vi.unstubAllGlobals());

describe('HttpTranscriber', () => {
  it('uploads the original audio and forwards cancellation', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ text: '  hello  ' }));
    vi.stubGlobal('fetch', fetchMock);
    const signal = new AbortController().signal;
    expect(await new HttpTranscriber('/api/v1/').transcribe(recording, signal)).toBe('  hello  ');
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/transcriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'audio/webm' },
      body: recording.blob,
      signal,
    });
  });

  it('maps valid backend errors and malformed responses safely', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ kind: 'unsupported_audio', detail: 'private' }, { status: 415 }),
      )
      .mockResolvedValueOnce(new Response('gateway', { status: 502 }));
    vi.stubGlobal('fetch', fetchMock);
    const transcriber = new HttpTranscriber('/api/v1');
    await expect(
      transcriber.transcribe(recording, new AbortController().signal),
    ).rejects.toMatchObject({ kind: 'unsupported_audio', status: 415 });
    await expect(
      transcriber.transcribe(recording, new AbortController().signal),
    ).rejects.toBeInstanceOf(TranscriptionError);
  });
});

it('accepts empty text and rejects invalid successful payloads without retry', async () => {
  const fetchMock = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ text: '' }))
    .mockResolvedValueOnce(Response.json({ text: 42 }))
    .mockResolvedValueOnce(new Response('not json', { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  const transcriber = new HttpTranscriber('https://example.test/api/v1///');
  const signal = new AbortController().signal;
  await expect(transcriber.transcribe(recording, signal)).resolves.toBe('');
  await expect(transcriber.transcribe(recording, signal)).rejects.toMatchObject({
    kind: 'invalid_response',
  });
  await expect(transcriber.transcribe(recording, signal)).rejects.toMatchObject({
    kind: 'invalid_response',
  });
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls[0][0]).toBe('https://example.test/api/v1/transcriptions');
});

it('distinguishes network failure from intentional abort', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new Error('private network detail'));
  vi.stubGlobal('fetch', fetchMock);
  const transcriber = new HttpTranscriber('/api/v1');
  await expect(
    transcriber.transcribe(recording, new AbortController().signal),
  ).rejects.toMatchObject({ kind: 'network' });
  const controller = new AbortController();
  controller.abort();
  await expect(transcriber.transcribe(recording, controller.signal)).rejects.toMatchObject({
    name: 'AbortError',
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('propagates abort while reading the response body', async () => {
  let resolveBody!: (value: unknown) => void;
  const body = new Promise<unknown>((resolve) => {
    resolveBody = resolve;
  });
  const response = new Response('{}');
  vi.spyOn(response, 'json').mockReturnValue(body);
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(response));
  const controller = new AbortController();
  const result = new HttpTranscriber('/api/v1').transcribe(recording, controller.signal);
  await Promise.resolve();
  controller.abort();
  resolveBody({ text: 'late' });
  await expect(result).rejects.toMatchObject({ name: 'AbortError' });
});
