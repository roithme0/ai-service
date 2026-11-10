import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { ImageGenerationUiComponent } from '@roithme0/image-generation/ui';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageGenerationDemo } from './image-generation-demo.component';

const running = {
  generation_id: 'd0c2ca12-1392-46af-896e-25ddbf3d7783',
  status: 'running',
  created_at: '2026-01-01T00:00:00Z',
  completed_at: null,
  configured_model: 'gpt-image-test',
  provider_model: null,
  estimated_cost_usd: null,
};

function setup() {
  TestBed.configureTestingModule({
    imports: [ImageGenerationDemo],
    providers: [provideRouter([])],
  });
  const fixture = TestBed.createComponent(ImageGenerationDemo);
  fixture.detectChanges();
  const ui = fixture.debugElement.query(By.directive(ImageGenerationUiComponent))
    .componentInstance as ImageGenerationUiComponent;
  return { fixture, ui };
}

afterEach(() => vi.unstubAllGlobals());

describe('Image generation demo composition', () => {
  it('publishes a definitive unavailable rejection without retrying', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json(
          { kind: 'image_generation_unavailable', detail: 'Image generation is unavailable' },
          { status: 503 },
        ),
      );
    vi.stubGlobal('fetch', fetcher);
    const { fixture, ui } = setup();
    expect(fetcher).not.toHaveBeenCalled();
    await ui.actions().submit('brief');
    fixture.detectChanges();
    expect(ui.state().admission).toBe('rejected');
    expect(ui.state().error).toBe('Image generation is unavailable');
    expect(fetcher).toHaveBeenCalledTimes(1);
    fixture.destroy();
  });

  it('recovers the original request with the same key, then reconnects without another submission', async () => {
    let posts = 0;
    const fetcher = vi.fn<typeof fetch>((input, init) => {
      if (init?.method === 'POST') {
        posts++;
        return posts === 1
          ? Promise.reject(new TypeError('connection lost'))
          : Promise.resolve(Response.json(running));
      }
      expect(input).toBe(`/api/v1/image-generations/${running.generation_id}/events`);
      return Promise.resolve(
        new Response('', { headers: { 'Content-Type': 'text/event-stream' } }),
      );
    });
    vi.stubGlobal('fetch', fetcher);
    const { fixture, ui } = setup();
    await ui.actions().submit('  original brief  ');
    fixture.detectChanges();
    expect(ui.state().admission).toBe('uncertain');
    await ui.actions().recoverSubmission();
    await vi.waitFor(() => {
      fixture.detectChanges();
      expect(ui.state().observation).toBe('lost');
    });
    const first = fetcher.mock.calls[0][1]!;
    const second = fetcher.mock.calls[1][1]!;
    expect(first.body).toBe(JSON.stringify({ instructions: '  original brief  ' }));
    expect(second.body).toBe(first.body);
    const firstHeaders = new Headers(first.headers);
    const secondHeaders = new Headers(second.headers);
    expect(firstHeaders.get('X-Application-User')).toBe('demo:default');
    expect(firstHeaders.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/i);
    expect(secondHeaders.get('Idempotency-Key')).toBe(firstHeaders.get('Idempotency-Key'));
    await ui.actions().reconnect();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(4));
    expect(posts).toBe(2);
    fixture.destroy();
  });

  it('aborts an in-flight submission when the route is destroyed', async () => {
    let signal: AbortSignal | null | undefined;
    const fetcher = vi.fn<typeof fetch>((_input, init) => {
      signal = init?.signal;
      return new Promise<Response>((_resolve, reject) =>
        signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true }),
      );
    });
    vi.stubGlobal('fetch', fetcher);
    const { fixture, ui } = setup();
    const pending = ui.actions().submit('brief');
    expect(signal?.aborted).toBe(false);
    fixture.destroy();
    expect(signal?.aborted).toBe(true);
    await pending;
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
