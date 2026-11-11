import { TestBed } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { registerUiIcons } from '../../../../../shared/icons';
import { afterEach, expect, it, vi } from 'vitest';
import type { RecordingOutcome, RecordingState } from '@roithme0/chat-ui/recording';
import type { DictationConfig } from '../../dictation';
import { ComposerComponent } from './composer.component';

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}
const audio = {
  blob: new Blob(['audio'], { type: 'audio/webm' }),
  mimeType: 'audio/webm',
  durationMs: 10,
  stopReason: 'manual' as const,
};
afterEach(() => vi.unstubAllGlobals());
function setup() {
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
  TestBed.configureTestingModule({ imports: [ComposerComponent] });
  registerUiIcons(TestBed.inject(MatIconRegistry), TestBed.inject(DomSanitizer));
  const fixture = TestBed.createComponent(ComposerComponent);
  fixture.componentRef.setInput('mascotSource', '/mascot.png');
  fixture.componentRef.setInput('dictation', config);
  fixture.componentRef.setInput('dictationContextKey', 'first');
  fixture.detectChanges();
  const root = fixture.nativeElement as HTMLElement;
  const textarea = root.querySelector('textarea')!;
  const mic = (): HTMLButtonElement => root.querySelector<HTMLButtonElement>('.microphone-button')!;
  const edit = (value: string): void => {
    textarea.value = value;
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  };
  return {
    fixture,
    root,
    textarea,
    mic,
    edit,
    capture,
    transcript,
    recorder,
    transcribe,
    onError,
    publish: (state: RecordingState): void => {
      publish(state);
      fixture.detectChanges();
    },
  };
}

it.each([
  ['', '  hello  ', 'hello'],
  ['draft', '  hello\nworld  ', 'draft hello\nworld'],
  ['draft ', ' hello ', 'draft hello'],
  ['draft\n', ' hello ', 'draft\nhello'],
  ['draft', '  \n ', 'draft'],
])('appends the normalized transcript to the latest draft', async (draft, text, expected) => {
  const test = setup();
  test.edit('initial');
  const submissions: string[] = [];
  test.fixture.componentInstance.messageSubmitted.subscribe((value) =>
    submissions.push(value.text),
  );
  test.mic().click();
  test.fixture.detectChanges();
  test.root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  test.textarea.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
  );
  expect(submissions).toEqual([]);
  test.publish('recording');
  test.mic().click();
  expect(test.recorder.stop).toHaveBeenCalledOnce();
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  test.edit(draft);
  test.transcript.resolve(text);
  await test.fixture.whenStable();
  test.fixture.detectChanges();
  expect(test.textarea.value).toBe(expected);
  expect(submissions).toEqual([]);
  if (expected.trim()) {
    test.root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(submissions).toEqual([expected.trim()]);
  }
});

it('suppresses late transcription after a context change before effects run', async () => {
  const test = setup();
  test.edit('original');
  test.mic().click();
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await Promise.resolve();
  expect(test.transcribe).toHaveBeenCalledOnce();
  test.fixture.componentRef.setInput('dictationContextKey', 'second');
  test.transcript.resolve('stale');
  await test.fixture.whenStable();
  test.fixture.detectChanges();
  expect(test.textarea.value).toBe('original');
  expect(test.onError).not.toHaveBeenCalled();
});

it.each(['context', 'config', 'editingDisabled'] as const)(
  'discards capture before rendering a parent %s change',
  async (cause) => {
    const test = setup();
    test.mic().click();
    if (cause === 'context') test.fixture.componentRef.setInput('dictationContextKey', 'second');
    if (cause === 'config') test.fixture.componentRef.setInput('dictation', null);
    if (cause === 'editingDisabled') test.fixture.componentRef.setInput('editingDisabled', true);
    test.capture.resolve({ kind: 'recorded', recording: audio });
    await Promise.resolve();
    expect(test.transcribe).not.toHaveBeenCalled();
    expect(test.onError).not.toHaveBeenCalled();
    await test.fixture.whenStable();
  },
);

it.each(['context', 'config', 'editingDisabled'] as const)(
  'suppresses transcription failures before rendering a parent %s change',
  async (cause) => {
    const test = setup();
    let reject!: (reason: Error) => void;
    const pending = new Promise<string>((_resolve, fail) => {
      reject = fail;
    });
    test.transcribe.mockReturnValue(pending);
    test.mic().click();
    test.capture.resolve({ kind: 'recorded', recording: audio });
    await Promise.resolve();
    if (cause === 'context') test.fixture.componentRef.setInput('dictationContextKey', 'second');
    if (cause === 'config') test.fixture.componentRef.setInput('dictation', null);
    if (cause === 'editingDisabled') test.fixture.componentRef.setInput('editingDisabled', true);
    reject(new Error('late'));
    await Promise.resolve();
    expect(test.onError).not.toHaveBeenCalled();
    await test.fixture.whenStable();
  },
);

it('blocks submission synchronously while dictating and resumes when configuration is removed', async () => {
  const test = setup();
  test.edit('draft');
  const submissions: string[] = [];
  test.fixture.componentInstance.messageSubmitted.subscribe((value) =>
    submissions.push(value.text),
  );
  test.mic().click();
  test.root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  test.textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', cancelable: true }));
  expect(submissions).toEqual([]);
  test.fixture.componentRef.setInput('dictation', null);
  test.fixture.detectChanges();
  expect(test.root.querySelector('.microphone-button')).toBeNull();
  test.root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  expect(submissions).toEqual(['draft']);
  test.capture.resolve({ kind: 'recorded', recording: audio });
  await test.fixture.whenStable();
  expect(test.transcribe).not.toHaveBeenCalled();
});
