import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpConversationTransport, ConversationApiError, ConversationNetworkError } from './conversation-api';

describe('HttpConversationTransport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each(['kochwiki', 'demo'])('uses %s for every path and sends its supplied input', async (configuration) => {
    const fetchMock = vi.fn().mockResolvedValue(
      response(201, {
        session_id: 'session-1',
        expires_at: '2026-09-17T12:00:00Z',
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const input = { marker: configuration };
    const transport = new HttpConversationTransport(configuration, input);
    const created = await transport.createSession();

    expect(created.session_id).toBe('session-1');
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/agents/${configuration}/sessions`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ input });
    fetchMock.mockResolvedValueOnce(response(200, {
      session_id: 'session-1', messages: [], artifacts: [], terminal_turn_id: null, terminal_turn_kind: null,
    })).mockResolvedValueOnce(response(201, { role: 'user', text: 'Hello' })).mockResolvedValueOnce(response(201, {
      kind: 'completed', turn_id: 'turn-1', message: { role: 'assistant', text: 'Hi', turn_id: 'turn-1' }, artifacts: [],
    }));
    await transport.readSession('session-1');
    await transport.appendMessage('session-1', 'Hello');
    await transport.generateTurn('session-1');
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      `/api/v1/agents/${configuration}/sessions`,
      `/api/v1/agents/${configuration}/sessions/session-1`,
      `/api/v1/agents/${configuration}/sessions/session-1/messages`,
      `/api/v1/agents/${configuration}/sessions/session-1/turns`,
    ]);
  });

  it('maps typed backend errors without accepting their payload as success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response(503, { kind: 'agent_unavailable' })),
    );

    await expect(new HttpConversationTransport('kochwiki', { source: {} }).generateTurn('session-1')).rejects.toEqual(
      expect.objectContaining<Partial<ConversationApiError>>({
        status: 503,
        kind: 'agent_unavailable',
      }),
    );
  });

  it('preserves an unrelated artifact envelope in history and turn results', async () => {
    const artifact = {
      artifact_id: 'artifact-1', type: 'other.result', created_at: '2026-09-25T12:00:00Z',
      order: 2, turn_id: 'turn-1', payload: { nested: [true, null, 4] },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response(200, {
          session_id: 'session-1',
          messages: [{ role: 'user', text: 'Weniger Zucker' }],
          artifacts: [artifact],
          terminal_turn_id: null,
          terminal_turn_kind: null,
        }),
      )
      .mockResolvedValueOnce(response(201, { role: 'user', text: 'Weniger Zucker' }))
      .mockResolvedValueOnce(
        response(201, {
          turn_id: 'turn-1',
          kind: 'completed',
          message: { role: 'assistant', text: 'Gern.', turn_id: 'turn-1' },
          artifacts: [artifact],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const transport = new HttpConversationTransport('kochwiki', { source: {} });

    await expect(transport.readSession('session-1')).resolves.toEqual({
      session_id: 'session-1',
      messages: [{ role: 'user', text: 'Weniger Zucker', turn_id: null }],
      artifacts: [artifact],
      terminal_turn_id: null,
      terminal_turn_kind: null,
    });
    await expect(transport.appendMessage('session-1', 'Weniger Zucker')).resolves.toEqual({
      role: 'user',
      text: 'Weniger Zucker',
      turn_id: null,
    });
    await expect(transport.generateTurn('session-1')).resolves.toEqual({
      turn_id: 'turn-1',
      kind: 'completed',
      message: { role: 'assistant', text: 'Gern.', turn_id: 'turn-1' },
      artifacts: [artifact],
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/agents/kochwiki/sessions/session-1',
      '/api/v1/agents/kochwiki/sessions/session-1/messages',
      '/api/v1/agents/kochwiki/sessions/session-1/turns',
    ]);
  });

  it('classifies malformed successful responses separately from API errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, {
      kind: 'completed', turn_id: 'turn-1', message: null, artifacts: [],
    })));
    await expect(new HttpConversationTransport('demo', null).generateTurn('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

});

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
