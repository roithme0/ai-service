import { JSON_ARTIFACT_CAPABILITY } from '@roithme0/chat-ui/ui';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoTransport } from './demo-transport';

describe('DemoTransport', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('delays native creation and admission while forwarding initialization and identity', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          { session_id: 'demo-1', expires_at: '2026-10-21T12:00:00Z' },
          { status: 201 },
        ),
      )
      .mockResolvedValueOnce(Response.json({ kind: 'accepted' }, { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    const transport = new DemoTransport();
    const initialization = {
      artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
    };
    const creation = transport.createSession(initialization);
    expect(fetchMock).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(500);
    await expect(creation).resolves.toMatchObject({ session_id: 'demo-1' });
    const submission = transport.submitPrompt('demo-1', 'Next');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(500);
    await expect(submission).resolves.toEqual({ kind: 'accepted' });
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/agents/demo/sessions',
      expect.objectContaining({ method: 'POST' }),
    );
    const body = fetchMock.mock.calls[0][1]?.body;
    expect(typeof body).toBe('string');
    expect(JSON.parse(body as string) as unknown).toEqual(initialization);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/agents/demo/sessions/demo-1/turns',
      expect.objectContaining({ body: JSON.stringify({ prompt: 'Next' }) }),
    );
    for (const [, options] of fetchMock.mock.calls)
      expect(new Headers(options?.headers).get('X-Application-User')).toBe('demo:default');
  });
});
