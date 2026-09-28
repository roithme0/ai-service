import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpConversationTransport, ConversationApiError, ConversationNetworkError, AgentConfiguration } from './conversation-api';

describe('HttpConversationTransport', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([AgentConfiguration.kochwiki, AgentConfiguration.demo])('uses %s for every path and sends its supplied input', async (configuration) => {
    const fetchMock = vi.fn().mockResolvedValue(
      response(201, {
        session_id: 'session-1',
        expires_at: '2026-09-17T12:00:00Z',
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const input = { marker: configuration };
    const transport = new HttpConversationTransport('/api/v1', configuration, input);
    const created = await transport.createSession();

    expect(created.session_id).toBe('session-1');
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/agents/${configuration}/sessions`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ input });
    fetchMock.mockResolvedValueOnce(response(200, {
      session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z',
      messages: [], artifacts: [], terminal_turn_id: null, terminal_turn_kind: null,
    })).mockResolvedValueOnce(response(201, { role: 'user', text: 'Hello', turn_id: null })).mockResolvedValueOnce(response(201, {
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

  it.each(['/api/v1', '/ai/api/v1/', 'https://example.test/ai/api/v1///'])('preserves the %s prefix and normalizes joining slashes', async (baseUrl) => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      session_id: 'session-1', expires_at: '2026-09-26T12:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);
    await new HttpConversationTransport(baseUrl, AgentConfiguration.demo).createSession();
    expect(fetchMock).toHaveBeenCalledWith(`${baseUrl.replace(/\/+$/, '')}/agents/demo/sessions`,
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ input: {} }) }));
  });

  it('classifies fetch and non-JSON failures as network errors', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(new Response('incomplete', { status: 502 }));
    vi.stubGlobal('fetch', fetchMock);
    const transport = new HttpConversationTransport('/api/v1', AgentConfiguration.demo);
    await expect(transport.createSession()).rejects.toBeInstanceOf(ConversationNetworkError);
    await expect(transport.createSession()).rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('maps typed backend errors without accepting their payload as success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response(503, { kind: 'agent_unavailable' })),
    );

    await expect(new HttpConversationTransport('/api/v1', 'kochwiki', { source: {} }).generateTurn('session-1')).rejects.toEqual(
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
          expires_at: '2026-09-17T12:00:00Z',
          messages: [{ role: 'user', text: 'Weniger Zucker', turn_id: null }],
          artifacts: [artifact],
          terminal_turn_id: null,
          terminal_turn_kind: null,
        }),
      )
      .mockResolvedValueOnce(response(201, { role: 'user', text: 'Weniger Zucker', turn_id: null }))
      .mockResolvedValueOnce(
        response(201, {
          turn_id: 'turn-1',
          kind: 'completed',
          message: { role: 'assistant', text: 'Gern.', turn_id: 'turn-1' },
          artifacts: [artifact],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const transport = new HttpConversationTransport('/api/v1', 'kochwiki', { source: {} });

    await expect(transport.readSession('session-1')).resolves.toEqual({
      session_id: 'session-1',
      expires_at: '2026-09-17T12:00:00Z',
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
    await expect(new HttpConversationTransport('/api/v1', 'demo', null).generateTurn('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('maps a validated invalid-input response to an API error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(422, {
      kind: 'invalid_input', issues: [{ location: ['input', 0], message: 'Invalid value' }],
    })));

    await expect(new HttpConversationTransport('/api/v1', AgentConfiguration.demo).createSession()).rejects.toEqual(
      expect.objectContaining<Partial<ConversationApiError>>({ status: 422, kind: 'invalid_input' }),
    );
  });

  it.each([
    { kind: 'future_kind' },
    { kind: 'invalid_input', issues: 'invalid' },
    { issues: [] },
  ])('classifies malformed error bodies as uncertain responses: %j', async (payload) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(422, payload)));

    await expect(new HttpConversationTransport('/api/v1', AgentConfiguration.demo).createSession())
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('rejects a user message without the required null turn_id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(201, { role: 'user', text: 'Hello' })));
    await expect(new HttpConversationTransport('/api/v1', 'demo').appendMessage('session-1', 'Hello'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('rejects a snapshot without its required expiry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, {
      session_id: 'session-1', messages: [], artifacts: [], terminal_turn_id: null, terminal_turn_kind: null,
    })));
    await expect(new HttpConversationTransport('/api/v1', 'demo').readSession('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('rejects a completed turn with a user message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(201, {
      kind: 'completed', turn_id: 'turn-1', message: { role: 'user', text: 'Hello', turn_id: null }, artifacts: [],
    })));
    await expect(new HttpConversationTransport('/api/v1', 'demo').generateTurn('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('rejects an artifact payload that is not an object', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, {
      session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z', messages: [],
      artifacts: [{ artifact_id: 'artifact-1', type: 'demo', created_at: '2026-09-17T12:00:00Z',
        order: 0, turn_id: 'turn-1', payload: [] }],
      terminal_turn_id: null, terminal_turn_kind: null,
    })));
    await expect(new HttpConversationTransport('/api/v1', 'demo').readSession('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('rejects a terminal turn kind outside the backend contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, {
      session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z', messages: [], artifacts: [],
      terminal_turn_id: 'turn-1', terminal_turn_kind: 'future_kind',
    })));
    await expect(new HttpConversationTransport('/api/v1', 'demo').readSession('session-1'))
      .rejects.toBeInstanceOf(ConversationNetworkError);
  });

  it('strips additive response fields while preserving extensible artifact payloads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(200, {
      session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z', future_field: true,
      messages: [{ role: 'user', text: 'Hello', turn_id: null, future_field: true }],
      artifacts: [{
        artifact_id: 'artifact-1', type: 'demo', created_at: '2026-09-17T12:00:00Z',
        order: 0, turn_id: 'turn-1', future_field: true, payload: { future_field: true },
      }],
      terminal_turn_id: null, terminal_turn_kind: null,
    })));

    await expect(new HttpConversationTransport('/api/v1', 'demo').readSession('session-1')).resolves.toEqual({
      session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z',
      messages: [{ role: 'user', text: 'Hello', turn_id: null }],
      artifacts: [{
        artifact_id: 'artifact-1', type: 'demo', created_at: '2026-09-17T12:00:00Z',
        order: 0, turn_id: 'turn-1', payload: { future_field: true },
      }],
      terminal_turn_id: null, terminal_turn_kind: null,
    });
  });
});

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
