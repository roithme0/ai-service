import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { afterEach, expect, it, vi } from 'vitest';
import type { RecordingOutcome, RecordingState } from '@roithme0/chat-ui/recording';
import { TranscriptionError } from '@roithme0/chat-ui/transcription';
import { registerUiIcons } from '../../../../../shared/icons';
import type { DictationConfig } from '../../dictation';
import { DictationButtonComponent, type DictationEnvironment } from './dictation-button.component';

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: Error) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const audio = {
  blob: new Blob(['audio'], { type: 'audio/webm' }),
  mimeType: 'audio/webm',
  durationMs: 10,
  stopReason: 'manual' as const,
};

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(document, 'hidden');
});

function setup(configure = true) {
  vi.stubGlobal('MediaRecorder', class {});
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } });
  const capture = deferred<RecordingOutcome>();
  const transcript = deferred<string>();
  let publish!: (state: RecordingState) => void;
  const recorder = {
    start: vi.fn(() => capture.promise),
    stop: vi.fn(),
    cancel: vi.fn(),
    dispose: vi.fn(),
  };
  const onError = vi.fn<DictationConfig['onError']>();
  const transcribe = vi.fn<DictationConfig['transcribe']>(() => transcript.promise);
  const config: DictationConfig = {
    createRecorder: (callback) => {
      publish = callback;
      return recorder;
    },
    transcribe,
    onError,
  };
  const environment = signal<DictationEnvironment>({
    config,
    contextKey: 'first',
    disabled: false,
    editingDisabled: false,
  });
  if (configure) {
    TestBed.configureTestingModule({ imports: [DictationButtonComponent] });
    registerUiIcons(TestBed.inject(MatIconRegistry), TestBed.inject(DomSanitizer));
  }
  const fixture = TestBed.createComponent(DictationButtonComponent);
  fixture.componentRef.setInput('source', environment);
  const emitted: string[] = [];
  fixture.componentInstance.transcribed.subscribe((text) => emitted.push(text));
  fixture.detectChanges();
  const root = fixture.nativeElement as HTMLElement;
  const mic = (): HTMLButtonElement => root.querySelector<HTMLButtonElement>('button')!;
  return {
    fixture,
    root,
    mic,
    capture,
    transcript,
    recorder,
    transcribe,
    onError,
    emitted,
    config,
    environment,
    update: (changes: Partial<DictationEnvironment>): void => {
      environment.update((value) => ({ ...value, ...changes }));
    },
    publish: (state: RecordingState): void => {
      publish(state);
      fixture.detectChanges();
    },
  };
}

it('stops capture, releases the recorder before transcription, and emits normalized text', async () => {
  const test = setup();
  test.mic().click();
  expect(test.fixture.componentInstance.busy()).toBe(true);
  test.fixture.detectChanges();
  expect(test.mic().disabled).toBe(true);
  test.publish('recording');
  expect(test.mic().getAttribute('aria-pressed')).toBe('true');
  test.mic().click();
  expect(test.recorder.stop).toHaveBeenCalledOnce();
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  expect(test.recorder.dispose).toHaveBeenCalledOnce();
  expect(test.transcribe).toHaveBeenCalledExactlyOnceWith(audio, expect.any(AbortSignal));
  expect(test.fixture.componentInstance.busy()).toBe(true);
  test.fixture.detectChanges();
  expect(test.mic().disabled).toBe(true);
  test.transcript.resolve('  hello\nworld  ');
  await test.fixture.whenStable();
  expect(test.emitted).toEqual(['hello\nworld']);
  expect(test.fixture.componentInstance.busy()).toBe(false);
  expect(test.recorder.dispose).toHaveBeenCalledOnce();
});

it('discards an empty transcript', async () => {
  const test = setup();
  test.mic().click();
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  test.transcript.resolve(' \n ');
  await test.fixture.whenStable();
  expect(test.emitted).toEqual([]);
  expect(test.fixture.componentInstance.busy()).toBe(false);
});

it('cancels capture on page hiding without uploading', async () => {
  const test = setup();
  test.mic().click();
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange'));
  expect(test.recorder.cancel).toHaveBeenCalledOnce();
  expect(test.recorder.dispose).toHaveBeenCalledOnce();
  expect(test.fixture.componentInstance.busy()).toBe(false);
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await test.fixture.whenStable();
  expect(test.transcribe).not.toHaveBeenCalled();
  expect(test.onError).not.toHaveBeenCalled();
});

it('allows stopping and finishing transcription while submission is disabled and page hides', async () => {
  const test = setup();
  test.mic().click();
  test.publish('recording');
  test.update({ disabled: true });
  test.fixture.detectChanges();
  expect(test.mic().disabled).toBe(false);
  test.mic().click();
  expect(test.recorder.stop).toHaveBeenCalledOnce();
  test.capture.resolve({ kind: 'recorded', recording: { ...audio, stopReason: 'duration-limit' } });
  await Promise.resolve();
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  document.dispatchEvent(new Event('visibilitychange'));
  test.transcript.resolve('result');
  await test.fixture.whenStable();
  expect(test.emitted).toEqual(['result']);
  expect(test.onError).not.toHaveBeenCalled();
});

it.each(['editingDisabled', 'configuration', 'context', 'destroy'] as const)(
  'cancels capture and silently discards late results after %s',
  async (cause) => {
    const test = setup();
    test.mic().click();
    if (cause === 'editingDisabled') test.update({ editingDisabled: true });
    if (cause === 'configuration') test.update({ config: null });
    if (cause === 'context') test.update({ contextKey: 'second' });
    if (cause === 'destroy') test.fixture.destroy();
    else test.fixture.detectChanges();
    expect(test.recorder.cancel).toHaveBeenCalledOnce();
    expect(test.recorder.dispose).toHaveBeenCalledOnce();
    test.capture.resolve({ kind: 'failed', error: 'capture-interrupted' });
    await Promise.resolve();
    expect(test.onError).not.toHaveBeenCalled();
    expect(test.transcribe).not.toHaveBeenCalled();
  },
);

it.each(['editingDisabled', 'configuration', 'context', 'destroy'] as const)(
  'aborts transcription and silently discards late results after %s',
  async (cause) => {
    const test = setup();
    test.mic().click();
    test.capture.resolve({ kind: 'recorded', recording: audio });
    await Promise.resolve();
    const signal = test.transcribe.mock.calls[0][1];
    if (cause === 'editingDisabled') test.update({ editingDisabled: true });
    if (cause === 'configuration') test.update({ config: null });
    if (cause === 'context') test.update({ contextKey: 'second' });
    if (cause === 'destroy') test.fixture.destroy();
    else test.fixture.detectChanges();
    expect(signal.aborted).toBe(true);
    test.transcript.resolve('obsolete');
    await Promise.resolve();
    expect(test.emitted).toEqual([]);
    expect(test.onError).not.toHaveBeenCalled();
    expect(test.recorder.dispose).toHaveBeenCalledOnce();
  },
);

it('reports a recording failure once and allows retry', async () => {
  const test = setup();
  test.mic().click();
  test.capture.resolve({ kind: 'failed', error: 'permission-denied' });
  await test.fixture.whenStable();
  test.fixture.detectChanges();
  expect(test.onError).toHaveBeenCalledExactlyOnceWith({
    kind: 'recording',
    reason: 'permission-denied',
  });
  expect(test.mic().disabled).toBe(false);
  const retry = deferred<RecordingOutcome>();
  test.recorder.start.mockReturnValue(retry.promise);
  test.mic().click();
  expect(test.recorder.start).toHaveBeenCalledTimes(2);
  retry.resolve({ kind: 'cancelled' });
  await test.fixture.whenStable();
  expect(test.onError).toHaveBeenCalledOnce();
});

it.each(['factory', 'start'] as const)(
  'contains a throwing recorder %s and restores ready state',
  async (phase) => {
    const test = setup();
    if (phase === 'factory') {
      test.update({
        config: {
          ...test.config,
          createRecorder: () => {
            throw new Error('factory failed');
          },
        },
      });
    } else {
      test.recorder.start.mockImplementation(() => {
        test.publish('recording');
        throw new Error('start failed');
      });
    }
    test.mic().click();
    await test.fixture.whenStable();
    test.fixture.detectChanges();
    expect(test.mic().getAttribute('aria-label')).toBe('Aufnahme starten');
    expect(test.mic().classList.contains('recording')).toBe(false);
    expect(test.fixture.componentInstance.busy()).toBe(false);
    expect(test.onError).toHaveBeenCalledExactlyOnceWith({
      kind: 'recording',
      reason: 'recorder-failed',
    });
    test.update({ config: test.config });
    test.recorder.start.mockImplementation(() => test.capture.promise);
    test.fixture.detectChanges();
    test.mic().click();
    expect(test.fixture.componentInstance.busy()).toBe(true);
    test.capture.resolve({ kind: 'cancelled' });
    await test.fixture.whenStable();
    expect(test.fixture.componentInstance.busy()).toBe(false);
    expect(test.onError).toHaveBeenCalledOnce();
  },
);

it('contains rejected capture and reports typed transcription failures', async () => {
  const test = setup();
  test.mic().click();
  test.publish('recording');
  test.capture.reject(new Error('capture failed'));
  await test.fixture.whenStable();
  test.fixture.detectChanges();
  expect(test.mic().getAttribute('aria-label')).toBe('Aufnahme starten');
  expect(test.onError).toHaveBeenCalledExactlyOnceWith({
    kind: 'recording',
    reason: 'recorder-failed',
  });
  const retry = deferred<RecordingOutcome>();
  test.recorder.start.mockReturnValue(retry.promise);
  test.mic().click();
  retry.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  test.transcript.reject(new TranscriptionError('invalid_response'));
  await test.fixture.whenStable();
  expect(test.onError).toHaveBeenLastCalledWith({
    kind: 'transcription',
    reason: 'invalid_response',
  });
});

it('invalidates obsolete recorder callbacks while a replacement remains busy', async () => {
  const test = setup();
  test.mic().click();
  const oldPublish = test.publish;
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  const signal = test.transcribe.mock.calls[0][1];
  const replacementCapture = deferred<RecordingOutcome>();
  let replacementPublish!: (state: RecordingState) => void;
  test.update({
    config: {
      createRecorder: (publish) => {
        replacementPublish = publish;
        return {
          start: () => replacementCapture.promise,
          stop: () => {},
          cancel: () => {},
          dispose: () => {},
        };
      },
      transcribe: () => Promise.resolve('new'),
      onError: test.onError,
    },
  });
  test.fixture.detectChanges();
  expect(signal.aborted).toBe(true);
  test.mic().click();
  replacementPublish('recording');
  test.fixture.detectChanges();
  oldPublish('ready');
  expect(test.mic().getAttribute('aria-label')).toBe('Aufnahme stoppen');
  test.transcript.resolve('obsolete');
  await Promise.resolve();
  expect(test.fixture.componentInstance.busy()).toBe(true);
  replacementCapture.resolve({ kind: 'recorded', recording: audio });
  await vi.waitFor(() => expect(test.emitted).toEqual(['new']));
  expect(test.onError).not.toHaveBeenCalled();
});

it('isolates recorder ownership between instances', async () => {
  const first = setup();
  const second = setup(false);
  first.mic().click();
  second.mic().click();
  first.update({ contextKey: 'changed' });
  first.fixture.detectChanges();
  expect(first.recorder.cancel).toHaveBeenCalledOnce();
  expect(first.recorder.dispose).toHaveBeenCalledOnce();
  expect(second.recorder.cancel).not.toHaveBeenCalled();
  second.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  second.transcript.resolve('second');
  await second.fixture.whenStable();
  expect(second.emitted).toEqual(['second']);
  expect(first.emitted).toEqual([]);
  expect(second.recorder.dispose).toHaveBeenCalledOnce();
});

it.each(['absent', 'unsupported'] as const)('hides the microphone when %s', (cause) => {
  const test = setup();
  if (cause === 'absent') test.update({ config: null });
  else {
    vi.stubGlobal('MediaRecorder', undefined);
    test.update({ config: { ...test.config } });
  }
  test.fixture.detectChanges();
  expect(test.root.querySelector('button')).toBeNull();
});

it.each(['disabled', 'editingDisabled'] as const)('prevents starting while %s', (cause) => {
  const test = setup();
  test.update({ [cause]: true });
  test.fixture.detectChanges();
  expect(test.mic().disabled).toBe(true);
  test.mic().click();
  expect(test.recorder.start).not.toHaveBeenCalled();
});
