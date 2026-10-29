import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { DomSanitizer } from '@angular/platform-browser';
import { MatIconRegistry } from '@angular/material/icon';
import { beforeEach, expect, it } from 'vitest';
import { page, userEvent } from 'vitest/browser';
import { registerChatIcons } from '../../chat-icons';
import type { ChatSubmission } from '../../models/chat-message';
import { ComposerComponent } from './composer.component';

let fixture: ComponentFixture<ComposerComponent>;
let textarea: HTMLTextAreaElement;

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
