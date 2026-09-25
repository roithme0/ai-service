import { presentRecipeArtifact } from './recipe-chat-domain';
import { presentJsonArtifact } from './generic-artifact-mapper';
import { describe, expect, it, vi } from 'vitest';
import {
  ConversationApiError,
  ConversationNetworkError,
  type ApiMessage,
  type ConversationTransport,
  type SessionCreation,
  type SessionSnapshot,
  type TurnResult,
} from './conversation-api';
import { ConversationController, type ConversationViewState } from './conversation-controller';

const CREATED: SessionCreation = { session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z' };

class FakeTransport implements ConversationTransport {
  createSession = vi.fn<() => Promise<SessionCreation>>().mockResolvedValue(CREATED);
  readSession = vi.fn<(sessionId: string) => Promise<SessionSnapshot>>();
  appendMessage = vi.fn<(sessionId: string, text: string) => Promise<ApiMessage>>();
  generateTurn = vi.fn<(sessionId: string) => Promise<TurnResult>>();
}

describe('ConversationController', () => {
  it('maps synthetic artifacts in order for successful turns and reconciled history', async () => {
    const transport = new FakeTransport();
    const later = {
      artifact_id: 'later', type: 'other.result', created_at: '2026-09-25T12:00:00Z',
      order: 2, turn_id: 'turn-1', payload: { value: 2 },
    };
    const earlier = { ...later, artifact_id: 'earlier', order: 1, payload: { value: 1 } };
    transport.appendMessage.mockResolvedValueOnce(user('Hello')).mockResolvedValueOnce(user('Again'));
    transport.generateTurn.mockResolvedValueOnce({
      kind: 'completed', turn_id: 'turn-1', message: assistant('Hi', 'turn-1'), artifacts: [later, earlier],
    }).mockRejectedValueOnce(new ConversationNetworkError('Timeout'));
    transport.readSession.mockResolvedValue({
      ...snapshot([user('Hello'), assistant('Hi', 'turn-1'), user('Again')]),
      artifacts: [later, earlier],
    });
    const controller = new ConversationController(transport, presentJsonArtifact, () => undefined);
    await controller.start();
    await controller.submit('Hello', () => undefined);
    expect(controller.state.content.map((item) => item.id)).toEqual([
      'confirmed-0-user', 'earlier', 'later', 'assistant-turn-1',
    ]);
    await controller.submit('Again', () => undefined);
    expect(controller.state.content.map((item) => item.id)).toEqual([
      'confirmed-0-user', 'earlier', 'later', 'assistant-turn-1', 'confirmed-2-user',
    ]);
    expect(controller.state.status?.action?.id).toBe('retry-turn');
  });

  it('reconciles a busy turn and retains the retry action when its result is still unclear', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue(user('Hello'));
    transport.generateTurn.mockRejectedValueOnce(new ConversationApiError(409, 'busy')).mockResolvedValueOnce({
      kind: 'completed', turn_id: 'turn-1', message: assistant('Hi', 'turn-1'), artifacts: [],
    });
    transport.readSession.mockResolvedValue(snapshot([user('Hello')]));
    const controller = new ConversationController(transport, presentJsonArtifact, () => undefined);
    await controller.start();

    await controller.submit('Hello', () => undefined);
    expect(controller.state.status?.action?.id).toBe('retry-turn');
    expect(controller.state.composerDisabled).toBe(true);
    await controller.performAction('retry-turn');
    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(transport.generateTurn).toHaveBeenCalledTimes(2);
    expect(controller.state.content.map((item) => item.id)).toEqual([
      'confirmed-0-user', 'assistant-turn-1',
    ]);
    expect(controller.state.composerDisabled).toBe(false);
  });
  it('reports agent unavailability during session creation', async () => {
    const transport = new FakeTransport();
    transport.createSession.mockRejectedValue(new ConversationApiError(503, 'agent_unavailable'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);

    await controller.start();

    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).toBe('Der KI-Agent ist derzeit nicht verfügbar.');
    expect(controller.state.status?.action?.id).toBe('new-session');
  });

  it('reports agent unavailability during message append', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationApiError(503, 'agent_unavailable'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();

    await controller.submit('Frage', () => undefined);

    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).toBe('Der KI-Agent ist derzeit nicht verfügbar.');
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('preserves agent unavailability from a reconciliation read', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue(user('Frage'));
    transport.generateTurn.mockRejectedValue(new ConversationNetworkError('Timeout'));
    transport.readSession.mockRejectedValue(new ConversationApiError(503, 'agent_unavailable'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();

    await controller.submit('Frage', () => undefined);

    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.message).toBe('Der KI-Agent ist derzeit nicht verfügbar.');
    expect(controller.state.status?.action?.id).toBe('new-session');
  });

  it('starts empty and publishes an accepted turn without optimistic messages', async () => {
    const transport = new FakeTransport();
    const append = deferred<ApiMessage>();
    const turn = deferred<TurnResult>();
    transport.appendMessage.mockReturnValue(append.promise);
    transport.generateTurn.mockReturnValue(turn.promise);
    const states: ConversationViewState[] = [];
    const controller = new ConversationController(transport, presentRecipeArtifact, (state) => states.push(state));
    await controller.start();
    const acknowledge = vi.fn();

    const submission = controller.submit('Weniger Zucker', acknowledge);
    expect(controller.state.content).toEqual([]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(acknowledge).not.toHaveBeenCalled();

    append.resolve(user('Weniger Zucker'));
    await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());
    expect(texts(controller.state.content)).toEqual(['Weniger Zucker']);
    expect(controller.state.status?.message).toBe('Antwort wird erstellt …');

    turn.resolve({ kind: 'completed', turn_id: 'turn-1', message: assistant('Gern.', 'turn-1'), artifacts: [] });
    await submission;
    expect(texts(controller.state.content)).toEqual([
      'Weniger Zucker',
      'Gern.',
    ]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(states.at(-1)?.status).toBeNull();
  });

  it('places resolved proposals between the user and final assistant text', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue(user('Alternative'));
    transport.generateTurn.mockResolvedValue({
      kind: 'completed',
      turn_id: 'turn-1',
      message: assistant('Hier ist sie.', 'turn-1'),
      artifacts: [{
        artifact_id: 'proposal-1', type: 'recipe.proposal', created_at: '2026-09-25T12:00:00Z', order: 1, turn_id: 'turn-1',
        payload: { name: 'Neue Variante', base: { kind: 'source' }, recipe: {
          servings: 2, preptime: null, kcal: 100, carbs: 12, protein: 8, fat: 3,
          ingredients: [{ index: 1, amount: 50, foodstuff: {
            id: 1, name: 'Hafer', brand: null, unit: 'G', unitVerbose: 'g',
            kcal: 370, carbs: 60, protein: 13, fat: 7,
          }}],
          steps: [{ index: 1, description: 'Mischen.' }],
        } },
      }],
    });
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();

    await controller.submit('Alternative', () => undefined);

    expect(controller.state.content.map((item) => item.kind)).toEqual([
      'text', 'artifact', 'text',
    ]);
    expect(controller.state.content[1]).toEqual(expect.objectContaining({
      id: 'proposal-1', type: 'recipe-proposal', headline: 'Neue Variante',
    }));
  });

  it('reconciles an ambiguous append and never appends it a second time', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('Netzwerkfehler'));
    transport.readSession.mockResolvedValue(snapshot([user('Knuspriger')]));
    transport.generateTurn.mockResolvedValue({
      kind: 'completed',
      turn_id: 'turn-1',
      message: assistant('Ja.', 'turn-1'),
      artifacts: [],
    });
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('Knuspriger', acknowledge);

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(transport.readSession).toHaveBeenCalledOnce();
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(controller.state.content).toHaveLength(2);
  });

  it('preserves artifacts in their original turns when reconciling a later append', async () => {
    const transport = new FakeTransport();
    transport.appendMessage
      .mockResolvedValueOnce(user('Erste Frage'))
      .mockRejectedValueOnce(new ConversationNetworkError('Netzwerkfehler'));
    transport.generateTurn
      .mockResolvedValueOnce({
        kind: 'completed',
        turn_id: 'turn-1',
        message: assistant('Erste Antwort', 'turn-1'),
        artifacts: [proposal('proposal-1', 'turn-1')],
      })
      .mockResolvedValueOnce({
        kind: 'completed',
        turn_id: 'turn-2',
        message: assistant('Zweite Antwort', 'turn-2'),
        artifacts: [],
      });
    transport.readSession.mockResolvedValue({
      ...snapshot([
        user('Erste Frage'),
        assistant('Erste Antwort', 'turn-1'),
        user('Zweite Frage'),
      ]),
      artifacts: [proposal('proposal-1', 'turn-1')],
    });
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    await controller.submit('Erste Frage', () => undefined);

    await controller.submit('Zweite Frage', () => undefined);

    expect(controller.state.content.map((item) => item.id)).toEqual([
      'confirmed-0-user',
      'proposal-1',
      'assistant-turn-1',
      'confirmed-2-user',
      'assistant-turn-2',
    ]);
  });

  it('preserves the draft contract and history when appending fails', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationApiError(422, 'invalid_message'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('UngÃ¼ltige Nachricht', acknowledge);

    expect(acknowledge).not.toHaveBeenCalled();
    expect(controller.state.content).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.kind).toBe('error');
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('does not acknowledge or repeat an ambiguous append absent from the session', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationNetworkError('Netzwerkfehler'));
    transport.readSession.mockResolvedValue(snapshot([]));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('Nicht bestÃ¤tigt', acknowledge);

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(controller.state.content).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('offers a new session when the agent is unavailable', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue(user('Leichter'));
    transport.generateTurn
      .mockRejectedValueOnce(new ConversationApiError(503, 'agent_unavailable'))
      .mockResolvedValueOnce({
        kind: 'completed',
        turn_id: 'turn-1',
        message: assistant('Versuche das.', 'turn-1'),
        artifacts: [],
      });
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    await controller.submit('Leichter', () => undefined);

    expect(controller.state.status?.action?.id).toBe('new-session');
    await controller.performAction('new-session');

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(transport.generateTurn).toHaveBeenCalledTimes(1);
    expect(transport.createSession).toHaveBeenCalledTimes(2);
    expect(controller.state.content).toHaveLength(0);
  });

  it('does not offer generation retry after a recorded failure', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue(user('Ã„ndern'));
    transport.generateTurn.mockRejectedValue(new ConversationApiError(502, 'generation_failed'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    await controller.submit('Ã„ndern', () => undefined);

    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.action).toBeUndefined();
  });

  it('keeps the previous conversation visible until replacement creation succeeds', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationApiError(410, 'expired'));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();
    await controller.submit('Hallo', () => undefined);
    const replacement = deferred<SessionCreation>();
    transport.createSession.mockReturnValueOnce(replacement.promise);

    const restarting = controller.performAction('new-session');
    expect(controller.state.status?.message).toBe('Unterhaltung wird gestartet …');
    replacement.resolve({ session_id: 'session-2', expires_at: CREATED.expires_at });
    await restarting;

    expect(controller.state.content).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
  });

  it.each([
    ['expired', 410],
    ['unknown', 404],
    ['limit_reached', 409],
  ])('offers a new session after the terminal %s outcome', async (kind, status) => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new ConversationApiError(status, kind));
    const controller = new ConversationController(transport, presentRecipeArtifact, () => undefined);
    await controller.start();

    await controller.submit('Hallo', () => undefined);

    expect(controller.state.composerDisabled).toBe(true);
    expect(controller.state.status?.action).toEqual({
      id: 'new-session',
      label: 'Neue Unterhaltung starten',
    });
  });
});

function snapshot(messages: readonly ApiMessage[]): SessionSnapshot {
  return {
    session_id: 'session-1',
    messages,
    artifacts: [],
    terminal_turn_id: null,
    terminal_turn_kind: null,
  };
}

function proposal(
  proposalId: string,
  turnId: string,
) {
  return {
    artifact_id: proposalId,
    type: 'recipe.proposal',
    created_at: '2026-09-25T12:00:00Z',
    order: 1,
    turn_id: turnId,
    payload: { name: 'Neue Variante', base: { kind: 'source' }, recipe: {
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
          unit: 'G' as const,
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

function user(text: string): ApiMessage {
  return { role: 'user', text, turn_id: null };
}

function assistant(text: string, turnId: string): ApiMessage {
  return { role: 'assistant', text, turn_id: turnId };
}

function texts(content: readonly { readonly kind: string; readonly text?: string }[]): readonly string[] {
  return content.flatMap((item) => item.kind === 'text' && item.text !== undefined ? [item.text] : []);
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}
