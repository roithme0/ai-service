import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import { By } from '@angular/platform-browser';
import { App } from './app.component';

describe('Demo application', () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    { type: 'demo.greeting', payload: { message: 'Hello, World!' }, text: '"message": "Hello, World!"' },
    { type: 'demo.greetings', payload: { messages: Array.from({ length: 30 }, (_, index) => `Hello, Visitor ${index + 1}!`) },
      text: 'Hello, Visitor 30!' },
  ])('creates an empty demo session and renders $type through explicit JSON presentation', async ({ type, payload, text }) => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ session_id: 'demo-1', expires_at: '2026-09-26T12:00:00Z' }))
      .mockResolvedValueOnce(Response.json({ role: 'user', text: 'Any text', turn_id: null }))
      .mockResolvedValueOnce(Response.json({
        kind: 'completed', turn_id: 'turn-2',
        message: { role: 'assistant', text: 'Scripted reply', turn_id: 'turn-2' },
        artifacts: [{ artifact_id: 'greeting-1', type,
          created_at: '2026-09-26T12:00:00Z', order: 1, turn_id: 'turn-2',
          payload }],
      }));
    vi.stubGlobal('fetch', fetchMock);
    TestBed.configureTestingModule({ imports: [App] });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const chat = fixture.debugElement.query(By.directive(ChatUiComponent)).componentInstance as ChatUiComponent;
    expect(chat.conversationStatus()?.message).toBe('Unterhaltung wird gestartet …');
    expect(fixture.nativeElement.querySelector('.status-content').classList.contains('status-content--fade')).toBe(true);
    expect(chat.composerDisabled()).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
    await fixture.whenStable();
    fixture.detectChanges();
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(chat.composerDisabled()).toBe(false);
    }, { timeout: 2500 });
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/agents/demo/sessions', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ input: {} }),
    }));
    expect(chat.content()).toEqual([]);
    expect(chat.composerDisabled()).toBe(false);
    expect(document.activeElement).toBe(fixture.nativeElement.querySelector('textarea'));
    const acknowledge = vi.fn();
    const submission: ChatSubmission = { text: 'Any text', acknowledge };
    chat.messageSubmitted.emit(submission);
    fixture.detectChanges();
    expect(chat.conversationStatus()?.message).toBe('Nachricht wird gesendet …');
    expect(chat.composerDisabled()).toBe(true);
    expect(acknowledge).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(fetchMock).toHaveBeenCalledTimes(3);
    }, { timeout: 2000 });
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(chat.content()).toHaveLength(3);
    });
    expect(acknowledge).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v1/agents/demo/sessions/demo-1/messages',
      expect.objectContaining({ body: JSON.stringify({ text: 'Any text' }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/v1/agents/demo/sessions/demo-1/turns',
      expect.objectContaining({ method: 'POST' }));
    expect(chat.content().map((item) => item.id)).toEqual(['confirmed-0-user', 'greeting-1', 'assistant-turn-2']);
    expect(chat.content()[1]).toEqual({ kind: 'artifact', id: 'greeting-1', type: 'json',
      headline: type, payload: { value: payload } });
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('pre')?.textContent).toContain(text);
    expect(element.textContent).toContain('festen Skript ohne KI-Modell');
    expect(element.textContent).toContain('simulierten API-Fehler');
    expect(chat.composerDisabled()).toBe(false);
  });

  it('shows a no-op action for the demo generation error', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ session_id: 'demo-1', expires_at: '2026-09-26T12:00:00Z' }))
      .mockResolvedValueOnce(Response.json({ role: 'user', text: 'Show error', turn_id: null }))
      .mockResolvedValueOnce(Response.json({
        detail: 'Turn generation failed', kind: 'generation_failed', turn_id: 'turn-4',
      }, { status: 502 }));
    vi.stubGlobal('fetch', fetchMock);
    TestBed.configureTestingModule({ imports: [App] });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const chat = fixture.debugElement.query(By.directive(ChatUiComponent)).componentInstance as ChatUiComponent;
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(chat.composerDisabled()).toBe(false);
    }, { timeout: 2500 });

    chat.messageSubmitted.emit({ text: 'Show error', acknowledge: vi.fn() });
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(chat.conversationStatus()?.action?.id).toBe('demo-noop');
    }, { timeout: 2500 });
    const action = fixture.nativeElement.querySelector('.status-action') as HTMLButtonElement;
    expect(action.textContent).toContain('Demo-Aktion (ohne Funktion)');
    action.click();
    fixture.detectChanges();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(chat.conversationStatus()?.action?.id).toBe('demo-noop');
    expect(chat.composerDisabled()).toBe(false);
  });
});
