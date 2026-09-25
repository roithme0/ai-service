import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpRecipeChatTransport, RecipeChatApiError, RecipeChatNetworkError, parseRecipeArtifact } from './recipe-chat-api';

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
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/agents/kochwiki/sessions');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toHaveProperty('input.source');
  });

  it('maps typed backend errors without accepting their payload as success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(response(503, { kind: 'agent_unavailable' })),
    );

    await expect(new HttpRecipeChatTransport().generateTurn('session-1')).rejects.toEqual(
      expect.objectContaining<Partial<RecipeChatApiError>>({
        status: 503,
        kind: 'agent_unavailable',
      }),
    );
  });

  it('maps session snapshots, accepted messages, and turns with proposals', async () => {
    const proposal = proposalPayload();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response(200, {
          session_id: 'session-1',
          messages: [{ role: 'user', text: 'Weniger Zucker' }],
          artifacts: [proposal],
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
          artifacts: [proposal],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const transport = new HttpRecipeChatTransport();

    await expect(transport.readSession('session-1')).resolves.toEqual({
      session_id: 'session-1',
      messages: [{ role: 'user', text: 'Weniger Zucker', turn_id: null }],
      artifacts: [proposal],
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
      artifacts: [proposal],
    });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v1/agents/kochwiki/sessions/session-1',
      '/api/v1/agents/kochwiki/sessions/session-1/messages',
      '/api/v1/agents/kochwiki/sessions/session-1/turns',
    ]);
  });

  it.each([null, 'invalid', []])('rejects a recipe artifact with non-object payload %j', (payload) => {
    expect(() => parseRecipeArtifact({ ...proposalPayload(), payload })).toThrow(RecipeChatNetworkError);
  });

  it('ignores other artifact types without decoding their payload', () => {
    expect(parseRecipeArtifact({ ...proposalPayload(), type: 'demo.greeting', payload: null })).toBeNull();
  });
});

function proposalPayload() {
  return {
    artifact_id: 'proposal-1',
    type: 'recipe.proposal',
    created_at: '2026-09-25T12:00:00Z',
    order: 1,
    turn_id: 'turn-1',
    payload: { name: 'Leichtere Variante', base: { kind: 'source' }, recipe: {
      servings: 2,
      preptime: null,
      kcal: 100,
      carbs: 12,
      protein: 8,
      fat: 3,
      ingredients: [{
        index: 1,
        amount: 50,
        foodstuff: {
          id: 1,
          name: 'Hafer',
          brand: null,
          unit: 'G',
          unitVerbose: 'g',
          kcal: 370,
          carbs: 60,
          protein: 13,
          fat: 7,
        },
      }],
      steps: [{ index: 1, description: 'Mischen.' }],
    } },
  };
}

function response(status: number, payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
