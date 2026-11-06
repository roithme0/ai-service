import { expect, it, vi } from 'vitest';
import { BrowserAudioRecorder } from '../public-api';

it('encodes native audio, collects final data, and releases its captured track', async () => {
  const context = new AudioContext();
  const source = context.createOscillator();
  const destination = context.createMediaStreamDestination();
  source.connect(destination);
  const stream = destination.stream;
  const acquire = vi.spyOn(navigator.mediaDevices, 'getUserMedia').mockResolvedValue(stream);
  const recorder = new BrowserAudioRecorder();
  try {
    source.start();
    await context.resume();
    const result = recorder.start();
    await expect.poll(() => recorder.state).toBe('recording');
    await new Promise<void>((resolve) => setTimeout(resolve, 150));
    recorder.stop();
    const outcome = await result;
    expect(outcome.kind).toBe('recorded');
    if (outcome.kind !== 'recorded') throw new Error('Native recording failed');
    expect(outcome.recording.blob.size).toBeGreaterThan(0);
    expect(outcome.recording.mimeType).toBe(outcome.recording.blob.type);
    expect(outcome.recording.mimeType).toMatch(/^audio\//);
    expect(outcome.recording.stopReason).toBe('manual');
    expect(outcome.recording.durationMs).toBeGreaterThan(0);
    expect(stream.getTracks().every((track) => track.readyState === 'ended')).toBe(true);
    expect(recorder.state).toBe('ready');
    expect(acquire).toHaveBeenCalledExactlyOnceWith({ audio: true, video: false });
  } finally {
    recorder.dispose();
    source.stop();
    source.disconnect();
    stream.getTracks().forEach((track) => track.stop());
    await context.close();
    acquire.mockRestore();
  }
});
