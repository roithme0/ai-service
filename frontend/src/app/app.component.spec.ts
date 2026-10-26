import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { routes } from './app.routes';
import { DemoLanding } from './pages/demo-landing/demo-landing.component';
import { VisualDemo } from './pages/visual-demo/visual-demo.component';

describe('Demo navigation', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the selector without starting a session and leaves live navigation unwired', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>();
    vi.stubGlobal('fetch', fetch);
    TestBed.configureTestingModule({ providers: [provideRouter(routes)] });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/', DemoLanding);
    const page = harness.routeNativeElement!;
    expect(page.querySelector('h1')?.textContent).toBe('Choose a demo');
    expect(page.querySelector('a')?.getAttribute('href')).toBe('/demos/visual');
    page.querySelector<HTMLButtonElement>('button')!.click();
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('opens the visual page from its card, disposes observation on leaving, and starts fresh on return', async () => {
    const signals: AbortSignal[] = [];
    let sessionsCreated = 0;
    const fetch = vi.fn<typeof globalThis.fetch>((input, init): Promise<Response> => {
      const url = input instanceof Request ? input.url : input.toString();
      if (url.endsWith('/sessions')) {
        sessionsCreated += 1;
        return Promise.resolve(
          Response.json(
            {
              session_id: `session-${sessionsCreated}`,
              expires_at: '2026-10-27T12:00:00Z',
            },
            { status: 201 },
          ),
        );
      }
      if (url.endsWith('/events') && init?.signal) {
        const signal = init.signal;
        signals.push(signal);
        return Promise.resolve(
          new Response(
            new ReadableStream<Uint8Array>({
              start: (controller) => {
                signal.addEventListener('abort', () => controller.close(), { once: true });
              },
            }),
            { headers: { 'Content-Type': 'text/event-stream' } },
          ),
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal('fetch', fetch);
    TestBed.configureTestingModule({ providers: [provideRouter(routes)] });
    const harness = await RouterTestingHarness.create('/');
    harness.routeNativeElement!.querySelector<HTMLAnchorElement>('a')!.click();
    await vi.waitFor(() => expect(signals).toHaveLength(1), { timeout: 2500 });
    expect(TestBed.inject(Router).url).toBe('/demos/visual');
    expect(signals[0].aborted).toBe(false);
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/agents/visual-demo/sessions');
    await harness.navigateByUrl('/', DemoLanding);
    expect(signals[0].aborted).toBe(true);
    await harness.navigateByUrl('/demos/visual', VisualDemo);
    await vi.waitFor(() => expect(signals).toHaveLength(2), { timeout: 2500 });
    expect(sessionsCreated).toBe(2);
    await harness.navigateByUrl('/', DemoLanding);
    expect(signals[1].aborted).toBe(true);
  });
});
