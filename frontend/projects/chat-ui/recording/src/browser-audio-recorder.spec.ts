import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserAudioRecorder, MAX_RECORDING_DURATION_MS } from './browser-audio-recorder';
import type { RecordingState } from './recording-types';

class MicrophoneTrack extends EventTarget {
  readyState: MediaStreamTrackState = 'live';
  readonly stop = vi.fn((): void => {
    this.readyState = 'ended';
  });

  interrupt(): void {
    this.readyState = 'ended';
    this.dispatchEvent(new Event('ended'));
  }
}

class MicrophoneStream {
  readonly track = new MicrophoneTrack();
  getAudioTracks(): MicrophoneTrack[] {
    return [this.track];
  }
  getTracks(): MicrophoneTrack[] {
    return [this.track];
  }
  asNative(): MediaStream {
    return this as unknown as MediaStream;
  }
}

class NativeRecorder extends EventTarget {
  static instances: NativeRecorder[] = [];
  static constructionFailure = false;
  static startFailure = false;
  static stopFailure = false;
  state: MediaRecorder['state'] = 'inactive';
  readonly mimeType = 'audio/webm;codecs=opus';
  readonly stop = vi.fn((): void => {
    if (NativeRecorder.stopFailure) throw new Error('stop failed');
    this.state = 'inactive';
  });

  constructor(readonly stream: MediaStream) {
    super();
    if (NativeRecorder.constructionFailure) throw new Error('construction failed');
    NativeRecorder.instances.push(this);
  }

  start(): void {
    if (NativeRecorder.startFailure) throw new Error('start failed');
    this.state = 'recording';
  }

  data(value: string): void {
    const event = new Event('dataavailable');
    Object.defineProperty(event, 'data', { value: new Blob([value], { type: this.mimeType }) });
    this.dispatchEvent(event);
  }

  finish(): void {
    this.state = 'inactive';
    this.dispatchEvent(new Event('stop'));
  }
}

const access = vi.fn<MediaDevices['getUserMedia']>();
let stream: MicrophoneStream;
let subject: BrowserAudioRecorder;

beforeEach(() => {
  vi.useFakeTimers();
  NativeRecorder.instances = [];
  NativeRecorder.constructionFailure = false;
  NativeRecorder.startFailure = false;
  NativeRecorder.stopFailure = false;
  stream = new MicrophoneStream();
  access.mockReset().mockResolvedValue(stream.asNative());
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: access } });
  vi.stubGlobal('MediaRecorder', NativeRecorder);
  subject = new BrowserAudioRecorder();
});

afterEach(() => {
  subject.dispose();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function native(): NativeRecorder {
  const recorder = NativeRecorder.instances.at(-1);
  if (!recorder) throw new Error('Recorder was not created');
  return recorder;
}

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: Error) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

it('includes final native data, publishes lifecycle state, and transfers audio ownership', async () => {
  const states: RecordingState[] = [];
  subject = new BrowserAudioRecorder((state) => states.push(state));
  const result = subject.start();
  expect(subject.state).toBe('requesting-access');
  await Promise.resolve();
  expect(access).toHaveBeenCalledExactlyOnceWith({ audio: true, video: false });
  expect(subject.state).toBe('recording');
  native().data('first');
  vi.advanceTimersByTime(1234);
  subject.stop();
  expect(subject.state).toBe('finalizing');
  expect(stream.track.stop).not.toHaveBeenCalled();
  native().data('last');
  native().finish();
  const outcome = await result;
  expect(outcome.kind).toBe('recorded');
  if (outcome.kind !== 'recorded') throw new Error('Expected recording');
  expect(outcome.recording.blob.size).toBe(9);
  expect(outcome.recording.mimeType).toBe(native().mimeType);
  expect(outcome.recording.blob.type).toBe(outcome.recording.mimeType);
  expect(outcome.recording.durationMs).toBe(1234);
  expect(outcome.recording.stopReason).toBe('manual');
  expect(states).toEqual(['requesting-access', 'recording', 'finalizing', 'ready']);
  expect(stream.track.stop).toHaveBeenCalledOnce();
  expect(vi.getTimerCount()).toBe(0);
  subject.cancel();
  expect(outcome.recording.blob.size).toBe(9);
});

it('automatically finalizes after five recording minutes through the original completion promise', async () => {
  const permission = deferred<MediaStream>();
  access.mockReturnValueOnce(permission.promise);
  const result = subject.start();
  vi.advanceTimersByTime(400_000);
  permission.resolve(stream.asNative());
  await Promise.resolve();
  vi.advanceTimersByTime(MAX_RECORDING_DURATION_MS - 1);
  expect(native().stop).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(subject.state).toBe('finalizing');
  expect(native().stop).toHaveBeenCalledOnce();
  native().data('captured');
  native().finish();
  expect(await result).toMatchObject({
    kind: 'recorded',
    recording: {
      durationMs: MAX_RECORDING_DURATION_MS,
      stopReason: 'duration-limit',
    },
  });
});

it.each(['cancel', 'dispose', 'stop'] as const)(
  '%s settles pending permission immediately and releases a late grant without recording',
  async (action) => {
    const permission = deferred<MediaStream>();
    access.mockReturnValueOnce(permission.promise);
    const result = subject.start();
    subject[action]();
    expect(await result).toEqual({ kind: 'cancelled' });
    expect(subject.state).toBe(action === 'dispose' ? 'disposed' : 'ready');
    permission.resolve(stream.asNative());
    await Promise.resolve();
    expect(stream.track.stop).toHaveBeenCalledOnce();
    expect(NativeRecorder.instances).toHaveLength(0);
    expect(vi.getTimerCount()).toBe(0);
  },
);

it.each(['grant', 'reject'] as const)(
  'ignores a previous permission %s during a new capture',
  async (late) => {
    const permission = deferred<MediaStream>();
    const previous = new MicrophoneStream();
    access.mockReturnValueOnce(permission.promise);
    const first = subject.start();
    subject.cancel();
    expect(await first).toEqual({ kind: 'cancelled' });
    const second = subject.start();
    await Promise.resolve();
    if (late === 'grant') permission.resolve(previous.asNative());
    else permission.reject(new DOMException('denied', 'NotAllowedError'));
    await Promise.resolve();
    expect(subject.state).toBe('recording');
    expect(NativeRecorder.instances).toHaveLength(1);
    expect(previous.track.stop).toHaveBeenCalledTimes(late === 'grant' ? 1 : 0);
    subject.cancel();
    expect(await second).toEqual({ kind: 'cancelled' });
  },
);

it.each(['recording', 'finalizing'] as const)(
  'cancellation during %s discards data and ignores old events and timers after reuse',
  async (phase) => {
    const first = subject.start();
    await Promise.resolve();
    const old = native();
    old.data('discard');
    if (phase === 'finalizing') subject.stop();
    subject.cancel();
    expect(await first).toEqual({ kind: 'cancelled' });
    expect(stream.track.stop).toHaveBeenCalledOnce();
    stream = new MicrophoneStream();
    access.mockResolvedValueOnce(stream.asNative());
    const second = subject.start();
    await Promise.resolve();
    old.data('late');
    old.dispatchEvent(new Event('error'));
    old.finish();
    expect(subject.state).toBe('recording');
    expect(vi.getTimerCount()).toBe(1);
    subject.stop();
    native().data('new');
    native().finish();
    expect(await second).toMatchObject({ kind: 'recorded', recording: { blob: { size: 3 } } });
  },
);

it('rejects concurrent starts without touching capture and makes repeated terminal calls harmless', async () => {
  const result = subject.start();
  expect(await subject.start()).toEqual({ kind: 'failed', error: 'busy' });
  await Promise.resolve();
  subject.stop();
  subject.stop();
  expect(native().stop).toHaveBeenCalledOnce();
  subject.cancel();
  subject.cancel();
  subject.stop();
  expect(await result).toEqual({ kind: 'cancelled' });
  subject.dispose();
  subject.dispose();
  expect(await subject.start()).toEqual({ kind: 'failed', error: 'disposed' });
  expect(access).toHaveBeenCalledOnce();
});

describe('typed failures', () => {
  it.each(['navigator', 'MediaRecorder'] as const)(
    'safely reports missing %s without acquiring access',
    async (missing) => {
      vi.stubGlobal(missing, undefined);
      subject = new BrowserAudioRecorder();
      expect(subject.state).toBe('ready');
      expect(await subject.start()).toEqual({ kind: 'failed', error: 'unsupported' });
      expect(access).not.toHaveBeenCalled();
      expect(subject.state).toBe('ready');
    },
  );

  it.each([
    ['NotAllowedError', 'permission-denied'],
    ['SecurityError', 'permission-denied'],
    ['NotFoundError', 'microphone-unavailable'],
    ['NotReadableError', 'microphone-unavailable'],
  ] as const)('maps %s and permits another attempt', async (name, error) => {
    access.mockRejectedValueOnce(new DOMException('unavailable', name));
    expect(await subject.start()).toEqual({ kind: 'failed', error });
    const retry = subject.start();
    await Promise.resolve();
    expect(subject.state).toBe('recording');
    subject.cancel();
    expect(await retry).toEqual({ kind: 'cancelled' });
  });

  it.each(['constructionFailure', 'startFailure', 'stopFailure'] as const)(
    'cleans up after native %s',
    async (failure) => {
      NativeRecorder[failure] = true;
      const result = subject.start();
      await Promise.resolve();
      if (failure === 'stopFailure') subject.stop();
      expect(await result).toEqual({ kind: 'failed', error: 'recorder-failed' });
      expect(stream.track.stop).toHaveBeenCalledOnce();
      expect(subject.state).toBe('ready');
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each(['track', 'unexpected-stop', 'recorder-error'] as const)(
    'discards partial audio after %s',
    async (cause) => {
      const result = subject.start();
      await Promise.resolve();
      native().data('partial');
      if (cause === 'track') stream.track.interrupt();
      else if (cause === 'unexpected-stop') native().finish();
      else native().dispatchEvent(new Event('error'));
      expect(await result).toEqual({
        kind: 'failed',
        error: cause === 'recorder-error' ? 'recorder-failed' : 'capture-interrupted',
      });
      native().data('after failure');
      native().finish();
      expect(stream.track.stop).toHaveBeenCalledOnce();
      expect(subject.state).toBe('ready');
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it('rejects an already-ended microphone stream', async () => {
    stream.track.readyState = 'ended';
    expect(await subject.start()).toEqual({ kind: 'failed', error: 'microphone-unavailable' });
    expect(stream.track.stop).toHaveBeenCalledOnce();
    expect(NativeRecorder.instances).toHaveLength(0);
  });

  it('reports an empty final recording rather than publishing empty audio', async () => {
    const result = subject.start();
    await Promise.resolve();
    subject.stop();
    native().data('');
    native().finish();
    expect(await result).toEqual({ kind: 'failed', error: 'empty-recording' });
    expect(stream.track.stop).toHaveBeenCalledOnce();
  });
});

it.each(['requesting-access', 'recording', 'finalizing'] as const)(
  'allows a state observer to dispose reentrantly during %s',
  async (phase) => {
    subject = new BrowserAudioRecorder((state) => {
      if (state === phase) subject.dispose();
    });
    const result = subject.start();
    await Promise.resolve();
    if (phase === 'finalizing') subject.stop();
    expect(await result).toEqual({ kind: 'cancelled' });
    expect(subject.state).toBe('disposed');
    expect(vi.getTimerCount()).toBe(0);
    expect(stream.track.stop).toHaveBeenCalledTimes(phase === 'requesting-access' ? 0 : 1);
    expect(access).toHaveBeenCalledTimes(phase === 'requesting-access' ? 0 : 1);
  },
);

it('reports observer exceptions without breaking recording or cleanup', async () => {
  const report = vi.fn();
  vi.stubGlobal('reportError', report);
  const failure = new Error('observer failed');
  subject = new BrowserAudioRecorder(() => {
    throw failure;
  });
  const result = subject.start();
  await Promise.resolve();
  expect(subject.state).toBe('recording');
  subject.cancel();
  expect(await result).toEqual({ kind: 'cancelled' });
  expect(stream.track.stop).toHaveBeenCalledOnce();
  expect(report).toHaveBeenCalledWith(failure);
});
