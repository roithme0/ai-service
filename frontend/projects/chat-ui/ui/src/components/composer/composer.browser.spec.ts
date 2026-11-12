import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { beforeEach, expect, it, vi } from 'vitest';
import { page, userEvent } from 'vitest/browser';
import { registerUiIcons } from '../../../../../shared/icons';
import type { ChatSubmission } from '../../models/chat-message';
import type { ChatUsage } from '../../models/chat-usage';
import { ComposerComponent } from './composer.component';

let fixture: ComponentFixture<ComposerComponent>;
let textarea: HTMLTextAreaElement;

const USAGE: ChatUsage = {
  totalTokens: 0,
  estimatedCostUsd: null,
  inputTokens: 0,
  outputTokens: 0,
  reasoningTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  requests: 0,
  toolCalls: 0,
};

beforeEach(async () => {
  TestBed.configureTestingModule({ imports: [ComposerComponent, MatSnackBarModule] });
  registerUiIcons(TestBed.inject(MatIconRegistry), TestBed.inject(DomSanitizer));
  fixture = TestBed.createComponent(ComposerComponent);
  fixture.componentRef.setInput('mascotSource', '/images/mascot-idle.png');
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '100%';
  fixture.detectChanges();
  await fixture.whenStable();
  const element = host.querySelector('textarea');
  if (!element) throw new Error('Composer textarea is missing.');
  textarea = element;
});

it.each(['mouse', 'keyboard'] as const)(
  'uses native focus behavior when toggling stats with %s',
  async (interaction) => {
    const host = fixture.nativeElement as HTMLElement;
    host.style.marginTop = '400px';
    fixture.componentRef.setInput('usage', USAGE);
    fixture.detectChanges();
    await fixture.whenStable();
    const draft = page.getByRole('textbox', { name: 'Nachricht', exact: true });
    await draft.fill('Keep this draft');
    for (const label of ['Chat-Verbrauch anzeigen', 'Chat-Verbrauch einklappen']) {
      const toggle = page.getByRole('button', { name: label, exact: true });
      await expect.element(toggle).toBeVisible();
      if (interaction === 'mouse') {
        await draft.click();
        await toggle.click();
      } else {
        toggle.element().focus();
        await userEvent.keyboard('{Enter}');
      }
      await expect.poll(() => document.activeElement).toBe(document.body);
      await expect.element(draft).toHaveValue('Keep this draft');
    }
    await expect
      .element(page.getByRole('button', { name: 'Chat-Verbrauch anzeigen', exact: true }))
      .toHaveAttribute('aria-expanded', 'false');
  },
);

it('preserves composer focus when clicking Send', async () => {
  const submissions: ChatSubmission[] = [];
  fixture.componentInstance.messageSubmitted.subscribe((submission) =>
    submissions.push(submission),
  );
  const draft = page.getByRole('textbox', { name: 'Nachricht', exact: true });
  await draft.fill('Send this');
  await page.getByRole('button', { name: 'Nachricht senden', exact: true }).click();
  expect(submissions).toHaveLength(1);
  expect(document.activeElement).toBe(textarea);
  submissions[0].acknowledge();
  await expect.element(draft).toHaveValue('');
  expect(document.activeElement).toBe(textarea);
});

it('preserves multiline input until acknowledgement and blocks repeated Enter while pending', async () => {
  const submissions: ChatSubmission[] = [];
  fixture.componentInstance.messageSubmitted.subscribe((submission) => {
    submissions.push(submission);
    fixture.componentRef.setInput('disabled', true);
    fixture.componentRef.setInput('editingDisabled', true);
  });
  const draft = page.getByRole('textbox', { name: 'Nachricht', exact: true });
  const send = page.getByRole('button', { name: 'Nachricht senden', exact: true });
  const multiline = 'Erste Zeile\nZweite Zeile';

  await draft.fill('Erste Zeile');
  await userEvent.keyboard('{Shift>}{Enter}{/Shift}Zweite Zeile');
  await expect.element(draft).toHaveValue(multiline);
  expect(submissions).toHaveLength(0);

  await userEvent.keyboard('{Enter}');
  await expect.element(send).toBeDisabled();
  await userEvent.keyboard('{Enter}');
  expect(submissions.map(({ text }) => text)).toEqual([multiline]);
  await expect.element(draft).toHaveValue(multiline);

  submissions[0].acknowledge();
  fixture.componentRef.setInput('disabled', false);
  fixture.componentRef.setInput('editingDisabled', false);
  await expect.element(draft).toHaveValue('');
  await draft.fill('Next message');
  await expect.element(send).toBeEnabled();
});

it('grows with multiline input, caps at five rows with scrolling, and shrinks after clearing', async () => {
  const draft = page.getByRole('textbox', { name: 'Nachricht', exact: true });
  const height = (): number => textarea.getBoundingClientRect().height;
  const initialHeight = height();
  const lineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight);
  expect(initialHeight).toBeGreaterThan(0);
  expect(lineHeight).toBeGreaterThan(0);

  await draft.fill('First line\nSecond line');
  await expect.poll(height).toBeGreaterThan(initialHeight + lineHeight / 2);

  await draft.fill(Array.from({ length: 12 }, (_, index) => `Line ${index + 1}`).join('\n'));
  await expect.poll(height).toBeGreaterThan(initialHeight + 3 * lineHeight);
  await expect.poll(height).toBeLessThanOrEqual(initialHeight + 4 * lineHeight + 2);
  await expect.poll(() => textarea.scrollHeight).toBeGreaterThan(textarea.clientHeight);
  expect(getComputedStyle(textarea).overflowY).toBe('auto');
  textarea.scrollTop = textarea.scrollHeight;
  await expect.poll(() => textarea.scrollTop).toBeGreaterThan(0);

  await draft.fill('');
  await expect.poll(height).toBeLessThanOrEqual(initialHeight + 1);
});

it('keeps dictation controls accessible and blocks native keyboard submission', async () => {
  let resolve!: (outcome: import('@roithme0/chat-ui/recording').RecordingOutcome) => void;
  const promise = new Promise<import('@roithme0/chat-ui/recording').RecordingOutcome>(
    (complete) => {
      resolve = complete;
    },
  );
  let publish!: (state: import('@roithme0/chat-ui/recording').RecordingState) => void;
  const stop = vi.fn<() => void>();
  fixture.componentRef.setInput('dictation', {
    createRecorder: (
      callback: (state: import('@roithme0/chat-ui/recording').RecordingState) => void,
    ) => {
      publish = callback;
      return { start: () => promise, stop, cancel: () => {}, dispose: () => {} };
    },
    transcribe: () => Promise.resolve('spoken'),
    onError: () => {},
  });
  fixture.componentRef.setInput('model', {
    name: 'provider/' + 'long-model-identifier-'.repeat(12),
    reasoningEffort: 'high',
  });
  fixture.componentRef.setInput('dictationContextKey', 'context');
  fixture.detectChanges();
  const draft = page.getByRole('textbox', { name: 'Nachricht', exact: true });
  const start = page.getByRole('button', { name: 'Aufnahme starten', exact: true });
  const send = page.getByRole('button', { name: 'Nachricht senden', exact: true });
  const submissions: ChatSubmission[] = [];
  fixture.componentInstance.messageSubmitted.subscribe((value) => submissions.push(value));
  await draft.fill('draft');
  expect(start.element().closest('ai-chat-dictation-button')?.nextElementSibling).toBe(
    send.element(),
  );
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '320px';
  await expect
    .poll(
      () =>
        start.element().getBoundingClientRect().right <=
        send.element().getBoundingClientRect().left,
    )
    .toBe(true);
  expect(send.element().getBoundingClientRect().right).toBeLessThanOrEqual(
    host.getBoundingClientRect().right,
  );
  const metadata = host.querySelector('ai-chat-model-metadata');
  const effort = metadata?.querySelector('.effort');
  if (!(metadata instanceof HTMLElement) || !(effort instanceof HTMLElement))
    throw new Error('Metadata missing');
  expect(metadata.getBoundingClientRect().right).toBeLessThanOrEqual(
    start.element().getBoundingClientRect().left,
  );
  expect(effort.clientWidth).toBeGreaterThan(15);
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
  expect(
    Math.abs(
      start.element().getBoundingClientRect().top - send.element().getBoundingClientRect().top,
    ),
  ).toBeLessThan(2);
  const assertAligned = (): void => {
    const micRect = start.element().getBoundingClientRect();
    const sendRect = send.element().getBoundingClientRect();
    const micIcon = start.element().querySelector('mat-icon')!.getBoundingClientRect();
    const sendIcon = send.element().querySelector('mat-icon')!.getBoundingClientRect();
    expect(Math.abs(micRect.top - sendRect.top)).toBeLessThan(2);
    expect(Math.abs(micIcon.top - sendIcon.top)).toBeLessThan(2);
  };
  assertAligned();
  const snackBar = TestBed.inject(MatSnackBar).open('Recording error', 'OK');
  await expect.element(page.getByText('Recording error')).toBeVisible();
  assertAligned();
  snackBar.dismiss();
  assertAligned();
  await start.click();
  expect(document.activeElement).toBe(textarea);
  await expect.element(send).toBeDisabled();
  await draft.click();
  await userEvent.keyboard('{Enter}');
  expect(submissions).toHaveLength(0);
  publish('recording');
  fixture.detectChanges();
  const recording = page.getByRole('button', { name: 'Aufnahme stoppen', exact: true });
  await expect.element(recording).toHaveAttribute('aria-pressed', 'true');
  expect(recording.element().classList.contains('recording')).toBe(true);
  recording.element().focus();
  await userEvent.keyboard('{Enter}');
  expect(stop).toHaveBeenCalledOnce();
  resolve({
    kind: 'recorded',
    recording: {
      blob: new Blob(['audio'], { type: 'audio/webm' }),
      mimeType: 'audio/webm',
      durationMs: 10,
      stopReason: 'manual',
    },
  });
  await expect.element(draft).toHaveValue('draft spoken');
  expect(submissions).toHaveLength(0);
});

it.each([
  [320, null],
  [320, 'high'],
  [900, null],
  [900, 'high'],
] as const)(
  'keeps long model metadata accessible at %ipx with effort %s',
  async (width, reasoningEffort) => {
    const host = fixture.nativeElement as HTMLElement;
    host.style.width = `${width}px`;
    host.style.fontFamily = 'monospace';
    host.style.fontSize = '16px';
    host.style.lineHeight = '1.5';
    if (width === 900) host.style.setProperty('--ai-ui-composer-secondary-font-size', '13px');
    const name = 'provider/' + 'long-model-identifier-'.repeat(12);
    fixture.componentRef.setInput('model', { name, reasoningEffort });
    fixture.componentRef.setInput('usage', USAGE);
    fixture.detectChanges();
    await fixture.whenStable();
    const metadata = host.querySelector('ai-chat-model-metadata');
    if (!(metadata instanceof HTMLElement)) throw new Error('Metadata missing');
    const model = metadata.querySelector('.name');
    const effort = metadata.querySelector('.effort');
    if (!(model instanceof HTMLElement) || !(effort instanceof HTMLElement))
      throw new Error('Labels missing');
    const send = page.getByRole('button', { name: 'Nachricht senden', exact: true }).element();
    expect(model.textContent?.trim()).toBe('Modell: ' + name);

    const effortText = reasoningEffort ?? 'nicht festgelegt';
    expect(effort.textContent?.trim()).toBe('Reasoning: ' + effortText);
    expect(model.title).toBe(name);
    expect(effort.title).toBe(effortText);
    const separator = metadata.querySelector('.separator');
    if (!(separator instanceof HTMLElement)) throw new Error('Separator missing');
    expect(separator.textContent).toBe('\u00b7');
    expect(separator.getAttribute('aria-hidden')).toBe('true');
    expect(getComputedStyle(model).textTransform).toBe('uppercase');
    expect(getComputedStyle(effort).textTransform).toBe('uppercase');
    expect(getComputedStyle(model).fontSize).toBe(getComputedStyle(effort).fontSize);
    const usageLine = host.querySelector('ai-chat-usage-line');
    if (!(usageLine instanceof HTMLElement)) throw new Error('Usage line missing');
    expect(getComputedStyle(model).fontSize).toBe(getComputedStyle(usageLine).fontSize);
    expect(getComputedStyle(usageLine).fontFamily).toBe(getComputedStyle(textarea).fontFamily);
    if (width === 900) expect(getComputedStyle(usageLine).fontSize).toBe('13px');
    const chevron = host.querySelector('.usage-toggle mat-icon svg');
    if (!(chevron instanceof SVGSVGElement)) throw new Error('Usage chevron missing');
    const usageBounds = usageLine.getBoundingClientRect();
    const chevronBounds = chevron.getBoundingClientRect();
    expect(
      Math.abs(
        chevronBounds.top + chevronBounds.height / 2 - usageBounds.top - usageBounds.height / 2,
      ),
    ).toBeLessThan(1);
    expect(
      Math.abs(model.getBoundingClientRect().left - textarea.getBoundingClientRect().left),
    ).toBeLessThan(1);
    expect(Number.parseFloat(getComputedStyle(model).fontSize)).toBeLessThan(
      Number.parseFloat(getComputedStyle(textarea).fontSize),
    );
    const effortLabel = effort.querySelector('.visually-hidden');
    if (!(effortLabel instanceof HTMLElement)) throw new Error('Effort label missing');
    expect(effortLabel.getBoundingClientRect().width).toBeLessThanOrEqual(1);
    expect(model.getBoundingClientRect().right).toBeLessThanOrEqual(
      separator.getBoundingClientRect().left,
    );
    expect(separator.getBoundingClientRect().right).toBeLessThanOrEqual(
      effort.getBoundingClientRect().left,
    );
    expect(
      Math.abs(model.getBoundingClientRect().top - effort.getBoundingClientRect().top),
    ).toBeLessThan(2);
    expect(effort.scrollWidth).toBeLessThanOrEqual(effort.clientWidth);
    expect(metadata.getBoundingClientRect().right).toBeLessThanOrEqual(
      send.getBoundingClientRect().left,
    );
    expect(send.getBoundingClientRect().right).toBeLessThanOrEqual(
      host.getBoundingClientRect().right,
    );
    expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
    expect(metadata.querySelector('button, a, input, [tabindex]')).toBeNull();
    fixture.componentRef.setInput('model', null);
    fixture.detectChanges();
    expect(host.querySelector('ai-chat-model-metadata')).toBeNull();
  },
);
