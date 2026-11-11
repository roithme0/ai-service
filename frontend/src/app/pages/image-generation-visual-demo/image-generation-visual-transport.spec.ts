import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageGenerationVisualTransport } from './image-generation-visual-transport';
import { ImageGenerationController } from '@roithme0/image-generation/controller';

describe('ImageGenerationVisualTransport', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('recovers uncertain admission with the original key and stable completed identity', async () => {
    vi.useFakeTimers();
    const transport = new ImageGenerationVisualTransport('submission-uncertain');
    const signal = new AbortController().signal;
    const first = transport.submit('  original  ', 'key', signal);
    const rejection = expect(first).rejects.toMatchObject({ category: 'uncertain' });
    await vi.advanceTimersByTimeAsync(500);
    await rejection;
    await expect(transport.submit('different', 'key', signal)).rejects.toMatchObject({
      category: 'rejected',
    });
    const recovery = transport.submit('  original  ', 'key', signal);
    await vi.advanceTimersByTimeAsync(500);
    const completed = await recovery;
    expect(completed.status).toBe('completed');
    expect(await transport.read(completed.generation_id, signal)).toEqual(completed);
    const repeated = transport.submit('  original  ', 'key', signal);
    await vi.advanceTimersByTimeAsync(500);
    expect(await repeated).toEqual(completed);
  });

  it('reconnects the same generation after observation loss', async () => {
    vi.useFakeTimers();
    const transport = new ImageGenerationVisualTransport('connection-lost');
    const signal = new AbortController().signal;
    const submission = transport.submit('draw', 'key', signal);
    await vi.advanceTimersByTimeAsync(500);
    const running = await submission;
    const observation = transport.observe(running.generation_id, signal).next();
    const lost = expect(observation).rejects.toMatchObject({ category: 'observation' });
    await vi.advanceTimersByTimeAsync(2000);
    await lost;
    expect((await transport.read(running.generation_id, signal)).status).toBe('running');
    const reconnect = transport.observe(running.generation_id, signal).next();
    await vi.advanceTimersByTimeAsync(500);
    expect((await reconnect).value).toMatchObject({
      kind: 'snapshot',
      snapshot: { status: 'completed', generation_id: running.generation_id },
    });
  });

  it('cancels a pending submission', async () => {
    vi.useFakeTimers();
    const transport = new ImageGenerationVisualTransport('success');
    const controller = new AbortController();
    const pending = transport.submit('draw', 'key', controller.signal);
    const aborted = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await aborted;
    expect(vi.getTimerCount()).toBe(0);
  });

  it('recovers uncertain admission through the real controller with the original text and key', async () => {
    vi.useFakeTimers();
    const transport = new ImageGenerationVisualTransport('submission-uncertain');
    const submit = vi.spyOn(transport, 'submit');
    const controller = new ImageGenerationController(transport, () => {});
    const first = controller.submit('  original instructions  ');
    await vi.advanceTimersByTimeAsync(500);
    await first;
    expect(controller.state.admission).toBe('uncertain');
    const recovery = controller.recoverSubmission();
    await vi.advanceTimersByTimeAsync(500);
    await recovery;
    expect(controller.state.snapshot?.status).toBe('completed');
    expect(submit).toHaveBeenCalledTimes(2);
    expect(submit.mock.calls[1][0]).toBe('  original instructions  ');
    expect(submit.mock.calls[1][1]).toBe(submit.mock.calls[0][1]);
    controller.dispose();
  });

  it('keeps failed content on the same completed generation until an explicit retry', async () => {
    vi.useFakeTimers();
    const blob = new Blob([new Uint8Array(3093259)], { type: 'image/png' });
    const fetcher = vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(blob) });
    vi.stubGlobal('fetch', fetcher);
    const transport = new ImageGenerationVisualTransport('image-load-failure');
    const submit = vi.spyOn(transport, 'submit');
    const controller = new ImageGenerationController(transport, () => {});
    const admission = controller.submit('draw');
    await vi.advanceTimersByTimeAsync(500);
    await admission;
    await vi.advanceTimersByTimeAsync(2000);
    const snapshot = controller.state.snapshot;
    expect(snapshot?.status).toBe('completed');
    const first = controller.loadContent();
    const failure = expect(first).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(500);
    await failure;
    expect(controller.state.content).toBe('error');
    expect(fetcher).not.toHaveBeenCalled();
    const retry = controller.loadContent();
    await vi.advanceTimersByTimeAsync(500);
    expect((await retry).blob).toEqual(blob);
    expect(controller.state.snapshot).toEqual(snapshot);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1);
    controller.dispose();
  });

  it('disposes an observing controller without publishing a late result', async () => {
    vi.useFakeTimers();
    const publish = vi.fn();
    const controller = new ImageGenerationController(
      new ImageGenerationVisualTransport('success'),
      publish,
    );
    const admission = controller.submit('draw');
    await vi.advanceTimersByTimeAsync(500);
    await admission;
    const count = publish.mock.calls.length;
    controller.dispose();
    await vi.advanceTimersByTimeAsync(2000);
    expect(publish).toHaveBeenCalledTimes(count);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('deduplicates overlapping submissions and rejects conflicting reuse of their key', async () => {
    vi.useFakeTimers();
    const transport = new ImageGenerationVisualTransport('success');
    const signal = new AbortController().signal;
    const first = transport.submit('draw', 'same-key', signal);
    const duplicate = transport.submit('draw', 'same-key', signal);
    const conflict = transport.submit('different', 'same-key', signal);
    const rejected = expect(conflict).rejects.toMatchObject({ category: 'rejected' });
    await vi.advanceTimersByTimeAsync(500);
    expect((await first).generation_id).toBe((await duplicate).generation_id);
    await rejected;
  });
});
