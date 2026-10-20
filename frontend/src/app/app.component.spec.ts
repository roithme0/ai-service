import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import { By } from '@angular/platform-browser';
import { App } from './app.component';
import type { SessionSnapshotResponse } from '@roithme0/chat-ui/conversation';

describe('Demo application', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    {
      type: 'demo.greeting',
      payload: { message: 'Hello, World!' },
      text: '"message": "Hello, World!"',
    },
    {
      type: 'demo.greetings',
      payload: {
        messages: Array.from({ length: 30 }, (_, index) => `Hello, Visitor ${index + 1}!`),
      },
      text: 'Hello, Visitor 30!',
    },
  ])(
    'creates an empty demo session and renders $type through explicit JSON presentation',
    async ({ type, payload, text }) => {
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          Response.json({ session_id: 'demo-1', expires_at: '2026-09-26T12:00:00Z' }),
        )
        .mockResolvedValueOnce(Response.json({ role: 'user', text: 'Any text', turn_id: 'turn-2' }))
        .mockResolvedValueOnce(Response.json({ kind: 'accepted', turn_id: 'turn-2' }))
        .mockResolvedValueOnce(
          snapshotObservation({
            session_id: 'demo-1',
            expires_at: '2026-09-26T12:00:00Z',
            sequence: 10,
            turns: [
              {
                turn_id: 'turn-2',
                user_message_id: 'confirmed-0-user',
                status: 'completed',
                timeline: [
                  {
                    kind: 'message',
                    is_final: false,
                    id: 'confirmed-0-user',
                    role: 'user',
                    text: 'Any text',
                    turn_id: 'turn-2',
                  },
                  {
                    kind: 'intermediate',
                    turn_id: 'turn-2',
                    id: 'update-1',
                    text: "I'll create a greeting artifact.",
                  },
                  {
                    kind: 'tool',
                    turn_id: 'turn-2',
                    execution_id: 'call-1',
                    name: 'create_greeting',
                    status: 'completed',
                  },
                  {
                    kind: 'artifact',
                    turn_id: 'turn-2',
                    artifact: {
                      artifact_id: 'greeting-1',
                      type,
                      created_at: '2026-09-26T12:00:00Z',
                      order: 1,
                      turn_id: 'turn-2',
                      payload,
                    },
                  },
                  {
                    kind: 'intermediate',
                    turn_id: 'turn-2',
                    id: 'update-2',
                    text: "I'll demonstrate a failed tool call.",
                  },
                  {
                    kind: 'tool',
                    turn_id: 'turn-2',
                    execution_id: 'call-2',
                    name: 'create_greeting',
                    status: 'failed',
                  },
                  {
                    kind: 'message',
                    is_final: true,
                    turn_id: 'turn-2',
                    id: 'assistant-turn-2',
                    role: 'assistant',
                    text: 'Scripted reply',
                  },
                ],
              },
            ],
          }),
        );
      vi.stubGlobal('fetch', fetchMock);
      TestBed.configureTestingModule({ imports: [App] });
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      const chat = fixture.debugElement.query(By.directive(ChatUiComponent))
        .componentInstance as ChatUiComponent;
      expect(chat.conversationStatus()?.message).toBe('Unterhaltung wird gestartet …');
      expect(fixtureElement(fixture).querySelector('.content')!.classList.contains('fade')).toBe(
        true,
      );
      expect(chat.composerDisabled()).toBe(true);
      expect(fetchMock).not.toHaveBeenCalled();
      await fixture.whenStable();
      fixture.detectChanges();
      await vi.waitFor(
        () => {
          fixture.detectChanges();
          expect(chat.composerDisabled()).toBe(false);
        },
        { timeout: 2500 },
      );
      expect(fetchMock).toHaveBeenNthCalledWith(
        1,
        '/api/v1/agents/demo/sessions',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ input: {} }),
        }),
      );
      expect(chat.turns().flatMap((turn) => turn.content)).toEqual([]);
      expect(chat.composerDisabled()).toBe(false);
      expect(document.activeElement).not.toBe(fixtureElement(fixture).querySelector('textarea'));
      const acknowledge = vi.fn();
      const submission: ChatSubmission = { text: 'Any text', acknowledge };
      chat.messageSubmitted.emit(submission);
      fixture.detectChanges();
      expect(chat.conversationStatus()).toBeNull();
      expect(chat.composerDisabled()).toBe(true);
      expect(acknowledge).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await vi.waitFor(
        () => {
          fixture.detectChanges();
          expect(fetchMock).toHaveBeenCalledTimes(4);
        },
        { timeout: 2000 },
      );
      await vi.waitFor(() => {
        fixture.detectChanges();
        expect(chat.turns().flatMap((turn) => turn.content)).toHaveLength(7);
      });
      expect(acknowledge).toHaveBeenCalledOnce();
      expect(fetchMock).toHaveBeenNthCalledWith(
        2,
        '/api/v1/agents/demo/sessions/demo-1/messages',
        expect.objectContaining({ body: JSON.stringify({ text: 'Any text' }) }),
      );
      expect(fetchMock).toHaveBeenNthCalledWith(
        3,
        '/api/v1/agents/demo/sessions/demo-1/turns',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(
        chat
          .turns()
          .flatMap((turn) => turn.content)
          .map((item) => item.id),
      ).toEqual([
        'confirmed-0-user',
        'update-1',
        'tool-call-1',
        'greeting-1',
        'update-2',
        'tool-call-2',
        'assistant-turn-2',
      ]);
      expect(chat.turns().flatMap((turn) => turn.content)[3]).toEqual({
        kind: 'artifact',
        id: 'greeting-1',
        turnId: 'turn-2',
        type: 'json',
        headline: type,
        payload: { value: payload },
      });
      const element = fixtureElement(fixture);
      expect(element.querySelector('ai-chat-intermediate-message')?.textContent).toContain(
        "I'll create a greeting artifact.",
      );
      const rows = [
        ...element.querySelectorAll<HTMLElement>(
          '.messages > ai-chat-history-item > .collapse > .clip > .item-content > *',
        ),
      ];
      expect(rows[1].matches('ai-chat-intermediate-message')).toBe(true);
      expect(rows[2].matches('ai-chat-tool-call')).toBe(true);
      expect(rows[3].tagName).toBe('AI-CHAT-ARTIFACT-CARD');
      expect(rows[4].matches('ai-chat-intermediate-message')).toBe(true);
      expect(rows[5].querySelector('.status')?.textContent).toContain('Fehlgeschlagen');
      expect(rows[6].matches('ai-chat-assistant-message')).toBe(true);
      expect(element.querySelector('pre')?.textContent).toContain(text);
      expect(element.textContent).toContain('festen Skript ohne KI-Modell');
      expect(element.textContent).toContain('simulierten API-Fehler');
      expect(chat.composerDisabled()).toBe(false);
    },
  );

  it('shows a no-op action for the demo generation error', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json({ session_id: 'demo-1', expires_at: '2026-09-26T12:00:00Z' }),
      )
      .mockResolvedValueOnce(Response.json({ role: 'user', text: 'Show error', turn_id: 'turn-4' }))
      .mockResolvedValueOnce(Response.json({ kind: 'accepted', turn_id: 'turn-4' }))
      .mockResolvedValueOnce(
        snapshotObservation({
          session_id: 'demo-1',
          expires_at: '2026-09-26T12:00:00Z',
          sequence: 4,
          turns: [
            {
              turn_id: 'turn-4',
              user_message_id: 'confirmed-0-user',
              status: 'generation_failed',
              timeline: [
                {
                  kind: 'message',
                  is_final: false,
                  id: 'confirmed-0-user',
                  turn_id: 'turn-4',
                  role: 'user',
                  text: 'Show error',
                },
                {
                  kind: 'intermediate',
                  id: 'failed-update',
                  turn_id: 'turn-4',
                  text: 'This update remains visible after generation fails.',
                },
                { kind: 'failure', turn_id: 'turn-4' },
              ],
            },
          ],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    TestBed.configureTestingModule({ imports: [App] });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const chat = fixture.debugElement.query(By.directive(ChatUiComponent))
      .componentInstance as ChatUiComponent;
    await vi.waitFor(
      () => {
        fixture.detectChanges();
        expect(chat.composerDisabled()).toBe(false);
      },
      { timeout: 2500 },
    );

    chat.messageSubmitted.emit({ text: 'Show error', acknowledge: vi.fn() });
    await vi.waitFor(
      () => {
        fixture.detectChanges();
        expect(chat.conversationStatus()?.action?.id).toBe('demo-noop');
      },
      { timeout: 2500 },
    );
    const action = fixtureElement(fixture).querySelector('.action') as HTMLButtonElement;
    const element = fixtureElement(fixture);
    expect(element.querySelector('ai-chat-intermediate-message')?.textContent).toContain(
      'This update remains visible after generation fails.',
    );
    expect(element.querySelector('ai-chat-assistant-message')).toBeNull();
    expect(element.querySelectorAll('ai-chat-status.error')).toHaveLength(1);
    expect(action.textContent).toContain('Demo-Aktion (ohne Funktion)');
    action.click();
    fixture.detectChanges();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(chat.conversationStatus()?.action?.id).toBe('demo-noop');
    expect(chat.composerDisabled()).toBe(false);
    expect(element.querySelector('ai-chat-intermediate-message')?.textContent).toContain(
      'This update remains visible after generation fails.',
    );
  });
});

function snapshotObservation(snapshot: SessionSnapshotResponse): Response {
  const turn = snapshot.turns.at(-1)!;
  const initial = { kind: 'snapshot', turn_id: turn.turn_id, snapshot };
  const terminal = {
    kind: 'terminal',
    turn_id: turn.turn_id,
    sequence: snapshot.sequence,
    outcome: turn.status,
  };
  return new Response(`data: ${JSON.stringify(initial)}\n\ndata: ${JSON.stringify(terminal)}\n\n`, {
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

function fixtureElement<T>(fixture: ComponentFixture<T>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}
