import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import type { PresentedSession, SessionEvent } from '@roithme0/chat-ui/conversation';
import { ChatUiComponent, JSON_ARTIFACT_CAPABILITY } from '@roithme0/chat-ui/ui';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveDemo } from './live-demo.component';

const EMPTY_USAGE: PresentedSession['usage'] = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  requests: 0,
  tool_calls: 0,
  estimated_cost_usd: null,
};
const EMPTY: PresentedSession = {
  error: null,
  usage: EMPTY_USAGE,
  session_id: 'live-session',
  expires_at: '2026-10-27T12:00:00Z',
  history: [],
};
const LIFECYCLE = {
  run_id: 'run-1',
  status: 'completed' as const,
  started_at: '2026-10-26T10:00:00Z',
  finished_at: '2026-10-26T10:00:01Z',
};

class LiveDemoServer {
  private events!: ReadableStreamDefaultController<Uint8Array>;
  readonly fetch = vi.fn<typeof fetch>((input, init) => {
    const url = input instanceof Request ? input.url : input.toString();
    if (url.endsWith('/sessions'))
      return Promise.resolve(
        Response.json(
          { session_id: EMPTY.session_id, expires_at: EMPTY.expires_at },
          { status: 201 },
        ),
      );
    if (url.endsWith('/events'))
      return Promise.resolve(
        new Response(
          new ReadableStream<Uint8Array>({
            start: (controller) => {
              this.events = controller;
              init?.signal?.addEventListener('abort', () => controller.close(), { once: true });
              this.snapshot(EMPTY);
            },
          }),
          { headers: { 'Content-Type': 'text/event-stream' } },
        ),
      );
    if (url.endsWith('/turns'))
      return Promise.resolve(Response.json({ kind: 'accepted' }, { status: 202 }));
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });

  snapshot(snapshot: PresentedSession): void {
    const event: SessionEvent = { kind: 'snapshot', snapshot };
    this.events.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  }
}

function createPage(): { fixture: ComponentFixture<LiveDemo>; chat: ChatUiComponent } {
  TestBed.configureTestingModule({ imports: [LiveDemo], providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(LiveDemo);
  fixture.detectChanges();
  const chat = fixture.debugElement.query(By.directive(ChatUiComponent))
    .componentInstance as ChatUiComponent;
  return { fixture, chat };
}

async function render(fixture: ComponentFixture<LiveDemo>, condition: () => void): Promise<void> {
  await vi.waitFor(() => {
    fixture.detectChanges();
    condition();
  });
}

describe('Live demo application', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('starts only a live session, advertises JSON artifacts, and renders tool results and actual usage', async () => {
    const server = new LiveDemoServer();
    vi.stubGlobal('fetch', server.fetch);
    const { fixture, chat } = createPage();
    await render(fixture, () => expect(chat.composerDisabled()).toBe(false));
    expect(server.fetch).toHaveBeenCalledTimes(2);
    expect(server.fetch).toHaveBeenNthCalledWith(
      1,
      '/api/v1/agents/live-demo/sessions',
      expect.objectContaining({
        method: 'POST',
      }),
    );
    expect(new Headers(server.fetch.mock.calls[0][1]?.headers).get('X-Application-User')).toBe(
      'demo:default',
    );
    expect(JSON.parse(server.fetch.mock.calls[0][1]?.body as string) as unknown).toEqual({
      artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
    });
    expect(chat.turns()).toEqual([]);
    expect(chat.bannerTitle()).toBeUndefined();
    expect(chat.bannerDescription()).toBe(
      'Stelle eine Frage oder starte ein Gespräch mit dem KI-Modell. Bitte um ein JSON-Artefakt, um die Tool-Nutzung auszuprobieren.',
    );
    expect(chat.usage()?.estimatedCostUsd).toBeNull();
    const acknowledge = vi.fn();
    chat.messageSubmitted.emit({ text: 'Zeig mir ein JSON-Artefakt.', acknowledge });
    await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());
    expect(server.fetch).toHaveBeenNthCalledWith(
      3,
      '/api/v1/agents/live-demo/sessions/live-session/turns',
      expect.objectContaining({ body: JSON.stringify({ prompt: 'Zeig mir ein JSON-Artefakt.' }) }),
    );
    const usage: PresentedSession['usage'] = {
      input_tokens: 100,
      output_tokens: 50,
      total_tokens: 150,
      reasoning_tokens: 20,
      cache_read_tokens: 10,
      cache_write_tokens: 5,
      requests: 2,
      tool_calls: 1,
      estimated_cost_usd: '0.002',
    };
    server.snapshot({
      ...EMPTY,
      usage,
      history: [
        { part_kind: 'user-prompt', content: 'Zeig mir ein JSON-Artefakt.' },
        {
          part_kind: 'turn',
          usage,
          lifecycle: LIFECYCLE,
          parts: [
            { part_kind: 'text', content: 'Ich stelle die Daten zusammen.', phase: 'commentary' },
            {
              part_kind: 'tool-call',
              tool_call_id: 'call-1',
              tool_name: 'present_artifact',
              status: 'success',
            },
            {
              part_kind: 'artifact',
              artifact: {
                artifact_id: 'data-1',
                type: 'json',
                created_at: LIFECYCLE.finished_at,
                run_id: LIFECYCLE.run_id,
                content: { title: 'Daten', payload: { value: { message: 'Hallo!' } } },
              },
            },
            { part_kind: 'text', content: 'Hier sind die Daten.', phase: 'final_answer' },
          ],
        },
      ],
    });
    await render(fixture, () => expect(chat.usage()?.totalTokens).toBe(150));
    expect(chat.usage()).toEqual({
      inputTokens: 100,
      outputTokens: 50,
      totalTokens: 150,
      reasoningTokens: 20,
      cacheReadTokens: 10,
      cacheWriteTokens: 5,
      requests: 2,
      toolCalls: 1,
      estimatedCostUsd: '0.002',
    });
    expect(
      chat
        .turns()
        .flatMap((turn) => turn.content)
        .map((part) => part.kind),
    ).toEqual(['text', 'intermediate', 'tool', 'artifact', 'text']);
    const page = fixture.nativeElement as HTMLElement;
    expect(page.querySelector('app-demo-header')?.textContent).toContain('Live Demo');
    expect(page.querySelector('pre')?.textContent).toContain('"message": "Hallo!"');
    expect(page.querySelector('ai-chat-usage-line')?.textContent).toContain('$0.002');
    expect(chat.composerDisabled()).toBe(false);
  });

  it('keeps ordinary failed-turn handling and accepts messages after more than three completed runs', async () => {
    const server = new LiveDemoServer();
    vi.stubGlobal('fetch', server.fetch);
    const { fixture, chat } = createPage();
    await render(fixture, () => expect(chat.composerDisabled()).toBe(false));
    server.snapshot({
      ...EMPTY,
      history: Array.from({ length: 5 }, (_, index) => ({
        part_kind: 'turn',
        usage: EMPTY_USAGE,
        lifecycle: {
          ...LIFECYCLE,
          run_id: `run-${index}`,
          status: index === 4 ? 'failed' : 'completed',
        },
        parts: [{ part_kind: 'text', content: `Antwort ${index}`, phase: 'commentary' }],
      })),
    });
    await render(fixture, () => expect(chat.conversationStatus()?.kind).toBe('error'));
    expect(chat.conversationStatus()?.action).toBeUndefined();
    expect(chat.composerDisabled()).toBe(false);
    const acknowledge = vi.fn();
    chat.messageSubmitted.emit({ text: 'Weiter bitte.', acknowledge });
    await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce());
    expect(server.fetch).toHaveBeenLastCalledWith(
      '/api/v1/agents/live-demo/sessions/live-session/turns',
      expect.objectContaining({ body: JSON.stringify({ prompt: 'Weiter bitte.' }) }),
    );
  });

  it('uses the normal retry action when the live agent is unavailable', async () => {
    const server = new LiveDemoServer();
    server.fetch.mockResolvedValueOnce(
      Response.json({ kind: 'agent_unavailable' }, { status: 503 }),
    );
    vi.stubGlobal('fetch', server.fetch);
    const { fixture, chat } = createPage();
    await render(fixture, () => expect(chat.conversationStatus()?.action?.id).toBe('new-session'));
    expect(chat.composerDisabled()).toBe(true);
    chat.statusActionTriggered.emit('new-session');
    await render(fixture, () => expect(chat.composerDisabled()).toBe(false));
    expect(server.fetch).toHaveBeenCalledTimes(3);
    expect(chat.conversationStatus()).toBeNull();
    expect(JSON.parse(server.fetch.mock.calls[1][1]?.body as string) as unknown).toEqual({
      artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
    });
  });
});
