import { describe, expect, it, vi } from 'vitest';
import {
  RecipeChatApiError,
  RecipeChatNetworkError,
  type ApiMessage,
  type RecipeChatTransport,
  type SessionCreation,
  type SessionSnapshot,
  type TurnResult,
} from './recipe-chat-api';
import { RecipeChatController, type RecipeChatViewState } from './recipe-chat-controller';

const CREATED: SessionCreation = { session_id: 'session-1', expires_at: '2026-09-17T12:00:00Z' };

class FakeTransport implements RecipeChatTransport {
  createSession = vi.fn<() => Promise<SessionCreation>>().mockResolvedValue(CREATED);
  readSession = vi.fn<(sessionId: string) => Promise<SessionSnapshot>>();
  appendMessage = vi.fn<(sessionId: string, text: string) => Promise<ApiMessage>>();
  generateTurn = vi.fn<(sessionId: string) => Promise<TurnResult>>();
}

describe('RecipeChatController', () => {
  it('starts empty and publishes an accepted turn without optimistic messages', async () => {
    const transport = new FakeTransport();
    const append = deferred<ApiMessage>();
    const turn = deferred<TurnResult>();
    transport.appendMessage.mockReturnValue(append.promise);
    transport.generateTurn.mockReturnValue(turn.promise);
    const states: RecipeChatViewState[] = [];
    const controller = new RecipeChatController(transport, (state) => states.push(state));
    await controller.start();
    const acknowledge = vi.fn();

    const submission = controller.submit('Weniger Zucker', acknowledge);
    expect(controller.state.messages).toEqual([]);
    expect(controller.state.composerDisabled).toBe(true);
    expect(acknowledge).not.toHaveBeenCalled();

    append.resolve({ role: 'user', text: 'Weniger Zucker' });
    await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());
    expect(controller.state.messages.map((message) => message.text)).toEqual(['Weniger Zucker']);
    expect(controller.state.status?.message).toBe('Antwort wird erstellt …');

    turn.resolve({ turn_id: 'turn-1', message: { role: 'assistant', text: 'Gern.' } });
    await submission;
    expect(controller.state.messages.map((message) => message.text)).toEqual([
      'Weniger Zucker',
      'Gern.',
    ]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(states.at(-1)?.status).toBeNull();
  });

  it('reconciles an ambiguous append and never appends it a second time', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new RecipeChatNetworkError('Netzwerkfehler'));
    transport.readSession.mockResolvedValue(snapshot([{ role: 'user', text: 'Knuspriger' }]));
    transport.generateTurn.mockResolvedValue({
      turn_id: 'turn-1',
      message: { role: 'assistant', text: 'Ja.' },
    });
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('Knuspriger', acknowledge);

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(transport.readSession).toHaveBeenCalledOnce();
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(controller.state.messages).toHaveLength(2);
  });

  it('preserves the draft contract and history when appending fails', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new RecipeChatApiError(422, 'invalid_message'));
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('Ungültige Nachricht', acknowledge);

    expect(acknowledge).not.toHaveBeenCalled();
    expect(controller.state.messages).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.kind).toBe('error');
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('does not acknowledge or repeat an ambiguous append absent from the session', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new RecipeChatNetworkError('Netzwerkfehler'));
    transport.readSession.mockResolvedValue(snapshot([]));
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    const acknowledge = vi.fn();

    await controller.submit('Nicht bestätigt', acknowledge);

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(controller.state.messages).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
    expect(transport.generateTurn).not.toHaveBeenCalled();
  });

  it('retries only generation when the model is unavailable', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue({ role: 'user', text: 'Leichter' });
    transport.generateTurn
      .mockRejectedValueOnce(new RecipeChatApiError(503, 'generator_unavailable'))
      .mockResolvedValueOnce({
        turn_id: 'turn-1',
        message: { role: 'assistant', text: 'Versuche das.' },
      });
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    await controller.submit('Leichter', () => undefined);

    expect(controller.state.status?.action?.id).toBe('retry-turn');
    await controller.performAction('retry-turn');

    expect(transport.appendMessage).toHaveBeenCalledOnce();
    expect(transport.generateTurn).toHaveBeenCalledTimes(2);
    expect(controller.state.messages).toHaveLength(2);
  });

  it('does not offer generation retry after a recorded failure', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockResolvedValue({ role: 'user', text: 'Ändern' });
    transport.generateTurn.mockRejectedValue(new RecipeChatApiError(502, 'generation_failed'));
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    await controller.submit('Ändern', () => undefined);

    expect(controller.state.composerDisabled).toBe(false);
    expect(controller.state.status?.action).toBeUndefined();
  });

  it('keeps the previous conversation visible until replacement creation succeeds', async () => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new RecipeChatApiError(410, 'expired'));
    const controller = new RecipeChatController(transport, () => undefined);
    await controller.start();
    await controller.submit('Hallo', () => undefined);
    const replacement = deferred<SessionCreation>();
    transport.createSession.mockReturnValueOnce(replacement.promise);

    const restarting = controller.performAction('new-session');
    expect(controller.state.status?.message).toBe('Unterhaltung wird gestartet …');
    replacement.resolve({ session_id: 'session-2', expires_at: CREATED.expires_at });
    await restarting;

    expect(controller.state.messages).toEqual([]);
    expect(controller.state.composerDisabled).toBe(false);
  });

  it.each([
    ['expired', 410],
    ['unknown', 404],
    ['limit_reached', 409],
  ])('offers a new session after the terminal %s outcome', async (kind, status) => {
    const transport = new FakeTransport();
    transport.appendMessage.mockRejectedValue(new RecipeChatApiError(status, kind));
    const controller = new RecipeChatController(transport, () => undefined);
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
    terminal_turn_id: null,
    terminal_turn_kind: null,
  };
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolvePromise: (value: T) => void = () => undefined;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}
