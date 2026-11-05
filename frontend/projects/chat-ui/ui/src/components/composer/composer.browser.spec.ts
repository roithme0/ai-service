import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { beforeEach, expect, it } from 'vitest';
import { page, userEvent } from 'vitest/browser';
import { registerChatIcons } from '../../chat-icons';
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
  TestBed.configureTestingModule({ imports: [ComposerComponent] });
  registerChatIcons(TestBed.inject(MatIconRegistry), TestBed.inject(DomSanitizer));
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
