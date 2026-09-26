import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChatUiComponent, type ChatSubmission } from '@roithme0/chat-ui/ui';
import { By } from '@angular/platform-browser';
import { App } from './app.component';

describe('Demo application', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('creates an empty demo session and renders an accepted artifact through JSON fallback', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ session_id: 'demo-1', expires_at: '2026-09-26T12:00:00Z' }))
      .mockResolvedValueOnce(Response.json({ role: 'user', text: 'Any text', turn_id: null }))
      .mockResolvedValueOnce(Response.json({
        kind: 'completed', turn_id: 'turn-2',
        message: { role: 'assistant', text: 'Scripted reply', turn_id: 'turn-2' },
        artifacts: [{ artifact_id: 'greeting-1', type: 'demo.greeting',
          created_at: '2026-09-26T12:00:00Z', order: 1, turn_id: 'turn-2',
          payload: { message: 'Hello, World!' } }],
      }));
    vi.stubGlobal('fetch', fetchMock);
    TestBed.configureTestingModule({ imports: [App] });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v1/agents/demo/sessions', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ input: {} }),
    }));
    const chat = fixture.debugElement.query(By.directive(ChatUiComponent)).componentInstance as ChatUiComponent;
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(chat.composerDisabled()).toBe(false);
    });
    expect(chat.content()).toEqual([]);
    expect(chat.composerDisabled()).toBe(false);
    const acknowledge = vi.fn();
    const submission: ChatSubmission = { text: 'Any text', acknowledge };
    chat.messageSubmitted.emit(submission);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
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
    expect(chat.content()[1]).toEqual({ kind: 'artifact', id: 'greeting-1', type: 'demo.greeting',
      headline: 'demo.greeting', payload: { message: 'Hello, World!' } });
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('pre')?.textContent).toContain('"message": "Hello, World!"');
    expect(element.textContent).toContain('festen Skript ohne KI-Modell');
    expect(chat.composerDisabled()).toBe(false);
  });
});
