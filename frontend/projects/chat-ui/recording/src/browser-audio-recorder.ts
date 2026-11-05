import type { RecordingOutcome, RecordingState, RecordingStopReason } from './recording-types';

export const MAX_RECORDING_DURATION_MS = 5 * 60 * 1000;

interface Capture {
  readonly complete: (outcome: RecordingOutcome) => void;
  stream: MediaStream | null;
  recorder: MediaRecorder | null;
  chunks: Blob[];
  removeListeners: (() => void) | null;
  timer: ReturnType<typeof setTimeout> | null;
  startedAt: number;
  durationMs: number;
  stopReason: RecordingStopReason | null;
}

export class BrowserAudioRecorder {
  private currentState: RecordingState = 'ready';
  private capture: Capture | null = null;

  constructor(private readonly publish: (state: RecordingState) => void = () => {}) {}

  get state(): RecordingState {
    return this.currentState;
  }

  start(): Promise<RecordingOutcome> {
    if (this.currentState === 'disposed')
      return Promise.resolve({ kind: 'failed', error: 'disposed' });
    if (this.capture) return Promise.resolve({ kind: 'failed', error: 'busy' });

    let complete!: (outcome: RecordingOutcome) => void;
    const completion = new Promise<RecordingOutcome>((resolve) => {
      complete = resolve;
    });
    const capture: Capture = {
      complete,
      stream: null,
      recorder: null,
      chunks: [],
      removeListeners: null,
      timer: null,
      startedAt: 0,
      durationMs: 0,
      stopReason: null,
    };
    this.capture = capture;
    this.setState('requesting-access');
    if (this.capture === capture) void this.acquire(capture);
    return completion;
  }

  stop(): void {
    const capture = this.capture;
    if (!capture) return;
    if (this.currentState === 'requesting-access') {
      this.cancel();
    } else if (this.currentState === 'recording') {
      this.finalize(capture, 'manual');
    }
  }

  cancel(): void {
    if (this.capture) this.finish(this.capture, { kind: 'cancelled' });
  }

  dispose(): void {
    if (this.currentState === 'disposed') return;
    const capture = this.capture;
    this.currentState = 'disposed';
    if (capture) this.finish(capture, { kind: 'cancelled' });
    this.setState('disposed');
  }

  private async acquire(capture: Capture): Promise<void> {
    if (
      typeof navigator === 'undefined' ||
      typeof navigator.mediaDevices?.getUserMedia !== 'function' ||
      typeof MediaRecorder === 'undefined'
    ) {
      this.finish(capture, { kind: 'failed', error: 'unsupported' });
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (error: unknown) {
      this.finish(capture, { kind: 'failed', error: microphoneError(error) });
      return;
    }
    if (this.capture !== capture) {
      releaseTracks(stream);
      return;
    }
    capture.stream = stream;
    const tracks = stream.getAudioTracks();
    if (tracks.length === 0 || tracks.some((track) => track.readyState === 'ended')) {
      this.finish(capture, { kind: 'failed', error: 'microphone-unavailable' });
      return;
    }

    try {
      const recorder = new MediaRecorder(stream);
      capture.recorder = recorder;
      this.observe(capture, recorder, tracks);
      recorder.start();
      if (this.capture !== capture) return;
      capture.startedAt = performance.now();
      capture.timer = setTimeout(
        () => this.finalize(capture, 'duration-limit'),
        MAX_RECORDING_DURATION_MS,
      );
      this.setState('recording');
    } catch {
      this.finish(capture, { kind: 'failed', error: 'recorder-failed' });
    }
  }

  private observe(capture: Capture, recorder: MediaRecorder, tracks: MediaStreamTrack[]): void {
    const data = (event: BlobEvent): void => {
      if (this.capture === capture && event.data.size > 0) capture.chunks.push(event.data);
    };
    const failed = (): void => this.finish(capture, { kind: 'failed', error: 'recorder-failed' });
    const interrupted = (): void =>
      this.finish(capture, { kind: 'failed', error: 'capture-interrupted' });
    const stopped = (): void => {
      if (this.capture !== capture) return;
      if (!capture.stopReason) {
        interrupted();
        return;
      }
      const mimeType = recorder.mimeType || capture.chunks[0]?.type || '';
      const blob = new Blob(capture.chunks, { type: mimeType });
      this.finish(
        capture,
        blob.size === 0
          ? { kind: 'failed', error: 'empty-recording' }
          : {
              kind: 'recorded',
              recording: {
                blob,
                mimeType: blob.type,
                durationMs: capture.durationMs,
                stopReason: capture.stopReason,
              },
            },
      );
    };
    recorder.addEventListener('dataavailable', data);
    recorder.addEventListener('error', failed);
    recorder.addEventListener('stop', stopped);
    tracks.forEach((track) => track.addEventListener('ended', interrupted));
    capture.removeListeners = () => {
      recorder.removeEventListener('dataavailable', data);
      recorder.removeEventListener('error', failed);
      recorder.removeEventListener('stop', stopped);
      tracks.forEach((track) => track.removeEventListener('ended', interrupted));
    };
  }

  private finalize(capture: Capture, stopReason: RecordingStopReason): void {
    if (this.capture !== capture || this.currentState !== 'recording') return;
    capture.stopReason = stopReason;
    capture.durationMs = Math.max(0, performance.now() - capture.startedAt);
    if (capture.timer !== null) clearTimeout(capture.timer);
    capture.timer = null;
    this.setState('finalizing');
    if (this.capture !== capture) return;
    try {
      if (!capture.recorder || capture.recorder.state === 'inactive') {
        this.finish(capture, { kind: 'failed', error: 'capture-interrupted' });
        return;
      }
      capture.recorder.stop();
    } catch {
      this.finish(capture, { kind: 'failed', error: 'recorder-failed' });
    }
  }

  private finish(capture: Capture, outcome: RecordingOutcome): void {
    if (this.capture !== capture) return;
    this.capture = null;
    if (capture.timer !== null) clearTimeout(capture.timer);
    capture.removeListeners?.();
    const recorder = capture.recorder;
    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        // Track cleanup must also run if native recorder shutdown fails.
      }
    }
    if (capture.stream) releaseTracks(capture.stream);
    capture.chunks = [];
    capture.stream = null;
    capture.recorder = null;
    capture.removeListeners = null;
    capture.timer = null;
    capture.complete(outcome);
    if (this.currentState !== 'disposed') this.setState('ready');
  }

  private setState(state: RecordingState): void {
    this.currentState = state;
    try {
      this.publish(state);
    } catch (error: unknown) {
      if (typeof globalThis.reportError === 'function') globalThis.reportError(error);
      else
        queueMicrotask(() => {
          throw error;
        });
    }
  }
}

function releaseTracks(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

function microphoneError(error: unknown): 'permission-denied' | 'microphone-unavailable' {
  if (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    (error.name === 'NotAllowedError' || error.name === 'SecurityError')
  ) {
    return 'permission-denied';
  }
  return 'microphone-unavailable';
}
