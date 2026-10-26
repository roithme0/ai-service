import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ChatUiComponent, JSON_ARTIFACT_CAPABILITY } from '@roithme0/chat-ui/ui';
import type { PresentedSession, SessionEvent } from '@roithme0/chat-ui/conversation';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { VisualDemo } from './visual-demo.component';

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
  session_id: 'visual-demo-1',
  expires_at: '2026-10-21T12:00:00Z',
  history: [],
};
const LIFECYCLE = {
  run_id: 'run-1',
  status: 'completed' as const,
  started_at: '2026-10-21T10:00:00Z',
  finished_at: '2026-10-21T10:00:01Z',
};

class VisualDemoServer {
  private events!: ReadableStreamDefaultController<Uint8Array>;
  readonly fetch = vi.fn<typeof fetch>((input) => {
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

async function openVisualDemo(): Promise<{
  fixture: ComponentFixture<VisualDemo>;
  chat: ChatUiComponent;
  server: VisualDemoServer;
}> {
  const server = new VisualDemoServer();
  vi.stubGlobal('fetch', server.fetch);
  TestBed.configureTestingModule({ imports: [VisualDemo] });
  const fixture = TestBed.createComponent(VisualDemo);
  fixture.detectChanges();
  const chat = fixture.debugElement.query(By.directive(ChatUiComponent))
    .componentInstance as ChatUiComponent;
  expect(chat.composerDisabled()).toBe(true);
  expect(chat.conversationStatus()?.kind).toBe('loading');
  await vi.waitFor(
    () => {
      fixture.detectChanges();
      expect(chat.composerDisabled()).toBe(false);
    },
    { timeout: 2500 },
  );
  return { fixture, chat, server };
}

function element(fixture: ComponentFixture<VisualDemo>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

async function render(fixture: ComponentFixture<VisualDemo>, condition: () => void): Promise<void> {
  await vi.waitFor(() => {
    fixture.detectChanges();
    condition();
  });
}

describe('Visual demo application', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('passes conversation totals from new snapshots to the composer usage line', async () => {
    const { fixture, chat, server } = await openVisualDemo();
    expect(chat.usage()).toMatchObject({ totalTokens: 0, estimatedCostUsd: null });
    server.snapshot({
      ...EMPTY,
      usage: {
        ...EMPTY_USAGE,
        input_tokens: 9600,
        output_tokens: 3200,
        total_tokens: 12800,
        reasoning_tokens: 1240,
        cache_read_tokens: 6400,
        cache_write_tokens: 800,
        requests: 8,
        tool_calls: 4,
        estimated_cost_usd: '0.024',
      },
    });
    await render(fixture, () => {
      const line = element(fixture).querySelector('ai-chat-composer ai-chat-usage-line');
      expect(line?.textContent).toContain('$0.024');
      expect(line?.textContent).toContain('12.8K Tokens');
    });
    expect(chat.usage()).toEqual({
      inputTokens: 9600,
      outputTokens: 3200,
      totalTokens: 12800,
      reasoningTokens: 1240,
      cacheReadTokens: 6400,
      cacheWriteTokens: 800,
      requests: 8,
      toolCalls: 4,
      estimatedCostUsd: '0.024',
    });
  });

  it.each<{ title: string; payload: Record<string, string | string[]>; text: string }>([
    {
      title: 'visual-demo.greeting',
      payload: { message: 'Hello, World!' },
      text: '"message": "Hello, World!"',
    },
    {
      title: 'visual-demo.greetings',
      payload: {
        messages: Array.from({ length: 30 }, (_, index) => `Hello, Visitor ${index + 1}!`),
      },
      text: 'Hello, Visitor 30!',
    },
  ])(
    'renders $title from native snapshots without inserting an optimistic prompt',
    async ({ title, payload, text }) => {
      const { fixture, chat, server } = await openVisualDemo();
      expect(server.fetch).toHaveBeenNthCalledWith(
        1,
        '/api/v1/agents/visual-demo/sessions',
        expect.objectContaining({
          method: 'POST',
        }),
      );
      const body = server.fetch.mock.calls[0][1]?.body;
      expect(typeof body).toBe('string');
      expect(JSON.parse(body as string) as unknown).toEqual({
        artifact_capabilities: [JSON_ARTIFACT_CAPABILITY],
      });
      const acknowledge = vi.fn();
      chat.messageSubmitted.emit({ text: 'Any text', acknowledge });
      fixture.detectChanges();
      expect(chat.composerEditingDisabled()).toBe(true);
      expect(chat.turns()).toEqual([]);
      await vi.waitFor(() => expect(acknowledge).toHaveBeenCalledOnce(), { timeout: 2500 });
      expect(chat.turns()).toEqual([]);
      expect(server.fetch).toHaveBeenNthCalledWith(
        3,
        '/api/v1/agents/visual-demo/sessions/visual-demo-1/turns',
        expect.objectContaining({ body: JSON.stringify({ prompt: 'Any text' }) }),
      );
      server.snapshot({
        ...EMPTY,
        history: [
          { part_kind: 'user-prompt', content: 'Any text' },
          {
            part_kind: 'turn',
            usage: EMPTY_USAGE,
            lifecycle: LIFECYCLE,
            parts: [
              { part_kind: 'text', content: 'Creating a greeting.', phase: 'commentary' },
              {
                part_kind: 'tool-call',
                tool_call_id: 'call-1',
                tool_name: 'present_artifact',
                status: 'success',
              },
              {
                part_kind: 'artifact',
                artifact: {
                  artifact_id: 'greeting-1',
                  type: 'json',
                  created_at: LIFECYCLE.finished_at,
                  run_id: 'run-1',
                  content: { title, payload: { value: payload } },
                },
              },
              {
                part_kind: 'tool-call',
                tool_call_id: 'call-2',
                tool_name: 'present_artifact',
                status: 'failed',
              },
              { part_kind: 'text', content: 'Scripted reply', phase: 'final_answer' },
            ],
          },
        ],
      });
      await render(fixture, () =>
        expect(chat.turns().flatMap((turn) => turn.content)).toHaveLength(6),
      );
      const content = chat.turns().flatMap((turn) => turn.content);
      expect(content.map((item) => item.kind)).toEqual([
        'text',
        'intermediate',
        'tool',
        'artifact',
        'tool',
        'text',
      ]);
      expect(content[3]).toEqual({
        kind: 'artifact',
        id: 'greeting-1',
        type: 'json',
        headline: title,
        payload: { value: payload },
      });
      expect(element(fixture).querySelector('pre')?.textContent).toContain(text);
      expect(element(fixture).querySelector('ai-chat-assistant-message')?.textContent).toContain(
        'Scripted reply',
      );
      expect(chat.composerDisabled()).toBe(false);
    },
  );

  it('retains failed-turn commentary and offers the no-op action', async () => {
    const { fixture, chat, server } = await openVisualDemo();
    server.snapshot({
      ...EMPTY,
      history: [
        { part_kind: 'user-prompt', content: 'Show error' },
        {
          part_kind: 'turn',
          usage: EMPTY_USAGE,
          lifecycle: { ...LIFECYCLE, status: 'failed' },
          parts: [
            { part_kind: 'text', content: 'This update remains visible.', phase: 'commentary' },
          ],
        },
      ],
    });
    await render(fixture, () =>
      expect(chat.conversationStatus()?.action?.id).toBe('visual-demo-noop'),
    );
    expect(element(fixture).querySelector('ai-chat-intermediate-message')?.textContent).toContain(
      'This update remains visible.',
    );
    expect(element(fixture).querySelector('ai-chat-assistant-message')).toBeNull();
    const requests = server.fetch.mock.calls.length;
    element(fixture).querySelector<HTMLButtonElement>('.action')!.click();
    fixture.detectChanges();
    expect(server.fetch).toHaveBeenCalledTimes(requests);
    expect(chat.composerDisabled()).toBe(false);
  });

  it('simulates incompatibility only after three completed runs and retains the snapshot and draft', async () => {
    const { fixture, chat, server } = await openVisualDemo();
    const history: PresentedSession['history'] = Array.from({ length: 4 }, (_, index) => ({
      part_kind: 'turn',
      usage: EMPTY_USAGE,
      lifecycle: {
        ...LIFECYCLE,
        run_id: `run-${index}`,
        status: index === 2 ? 'failed' : 'completed',
      },
      parts: [
        {
          part_kind: 'text',
          content: `Reply ${index}`,
          phase: index === 2 ? 'commentary' : 'final_answer',
        },
      ],
    }));
    server.snapshot({ ...EMPTY, history });
    await render(fixture, () => expect(chat.turns()).toHaveLength(4));
    const turns = chat.turns();
    const acknowledge = vi.fn();
    const requests = server.fetch.mock.calls.length;
    chat.messageSubmitted.emit({ text: 'After completion', acknowledge });
    fixture.detectChanges();
    expect(chat.conversationStatus()?.message).toBe('App und Backend sind nicht kompatibel.');
    expect(chat.composerDisabled()).toBe(true);
    expect(chat.composerEditingDisabled()).toBe(false);
    expect(chat.turns()).toBe(turns);
    expect(acknowledge).not.toHaveBeenCalled();
    server.snapshot({ ...EMPTY, history });
    await render(fixture, () =>
      expect(chat.conversationStatus()?.message).toBe('App und Backend sind nicht kompatibel.'),
    );
    expect(server.fetch).toHaveBeenCalledTimes(requests);
  });
});
