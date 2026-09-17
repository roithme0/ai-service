import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpRecipeChatTransport, RecipeChatApiError } from './recipe-chat-api';

describe('HttpRecipeChatTransport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the complete API prefix and maps a session creation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      response(201, {
        session_id: 'session-1',
        expires_at: '2026-09-17T12:00:00Z',
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const created = await new HttpRecipeChatTransport().createSession();

    expect(created.session_id).toBe('session-1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/recipe-improvement/sessions');
  });

  it('maps typed backend errors without accepting their payload as success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response(503, { kind: 'generator_unavailable' })),
    );

    await expect(new HttpRecipeChatTransport().generateTurn('session-1')).rejects.toEqual(
      expect.objectContaining<Partial<RecipeChatApiError>>({
        status: 503,
        kind: 'generator_unavailable',
      }),
    );
  });

  it('maps session snapshots, accepted messages, and turns while ignoring proposals', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response(200, {
          session_id: 'session-1',
          messages: [{ role: 'user', text: 'Weniger Zucker' }],
          terminal_turn_id: null,
          terminal_turn_kind: null,
          proposals: [{ proposal_id: 'not-rendered' }],
        }),
      )
      .mockResolvedValueOnce(response(201, { role: 'user', text: 'Weniger Zucker' }))
      .mockResolvedValueOnce(
        response(201, {
          turn_id: 'turn-1',
          message: { role: 'assistant', text: 'Gern.' },
          proposals: [{ proposal_id: 'not-rendered' }],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const transport = new HttpRecipeChatTransport();

    await expect(transport.readSession('session-1')).resolves.toEqual({
      session_id: 'session-1',
      messages: [{ role: 'user', text: 'Weniger Zucker' }],
      terminal_turn_id: null,
      terminal_turn_kind: null,
    });
    await expect(transport.appendMessage('session-1', 'Weniger Zucker')).resolves.toEqual({
      role: 'user',
      text: 'Weniger Zucker',
    });
    await expect(transport.generateTurn('session-1')).resolves.toEqual({
      turn_id: 'turn-1',
      message: { role: 'assistant', text: 'Gern.' },
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/recipe-improvement/sessions/session-1',
      '/api/v1/recipe-improvement/sessions/session-1/messages',
      '/api/v1/recipe-improvement/sessions/session-1/turns',
    ]);
  });
});

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
