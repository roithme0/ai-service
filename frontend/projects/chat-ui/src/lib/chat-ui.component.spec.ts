import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { CdkTextareaAutosize } from '@angular/cdk/text-field';
import { MatIconRegistry } from '@angular/material/icon';
import { firstValueFrom } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChatTextMessage } from './chat-message';
import { ChatUiComponent } from './chat-ui.component';

const INITIAL_MESSAGES: readonly ChatTextMessage[] = [
  { id: 'user-1', role: 'user', text: '**literal user text**' },
  { id: 'assistant-1', role: 'assistant', text: '**formatted assistant text**' },
];

describe('ChatUiComponent', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ChatUiComponent] });
  });

  it('renders ordered host messages and applies Markdown only to assistant text', () => {
    const fixture = createFixture(INITIAL_MESSAGES);
    const messageElements = fixture.nativeElement.querySelectorAll(
      '.message',
    ) as NodeListOf<HTMLElement>;

    expect(messageElements).toHaveLength(2);
    expect(messageElements[0].classList.contains('message--user')).toBe(true);
    expect(messageElements[0].textContent).toContain('**literal user text**');
    expect(messageElements[0].querySelector('strong')).toBeNull();
    expect(messageElements[1].classList.contains('message--assistant')).toBe(true);
    expect(messageElements[1].querySelector('strong')?.textContent).toBe(
      'formatted assistant text',
    );
  });

  it('emits one normalized submission and clears the composer', () => {
    const fixture = createFixture([]);
    const component = fixture.componentInstance;
    const emit = vi.spyOn(component.messageSubmitted, 'emit');
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;

    textarea.value = '  hello there  ';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(emit).toHaveBeenCalledOnce();
    expect(emit).toHaveBeenCalledWith('hello there');
    expect(textarea.value).toBe('');
    expect(fixture.nativeElement.querySelectorAll('.message')).toHaveLength(0);
    expect(document.activeElement).toBe(textarea);
  });

  it('autosizes the composer from one up to five lines', () => {
    const fixture = createFixture([]);
    const autosize = fixture.debugElement
      .query(By.directive(CdkTextareaAutosize))
      .injector.get(CdkTextareaAutosize);

    expect(autosize.minRows).toBe(1);
    expect(autosize.maxRows).toBe(5);
  });

  it('renders the packaged send icon through the Material control', () => {
    const fixture = createFixture([]);
    const button = fixture.nativeElement.querySelector('button[matIconButton]');
    const icon = fixture.nativeElement.querySelector('mat-icon[svgIcon="ai-chat:send"]');

    expect(button).not.toBeNull();
    expect(icon).not.toBeNull();
  });

  it('renders only the send action inside the composer surface', () => {
    const fixture = createFixture([]);
    const surface = fixture.nativeElement.querySelector('.composer-surface') as HTMLElement;
    const actions = surface.querySelector('.composer-actions') as HTMLElement;

    expect(surface.querySelector('textarea')).not.toBeNull();
    expect(actions.querySelectorAll('button')).toHaveLength(1);
    expect(actions.querySelector('.send-button')).not.toBeNull();
  });

  it('registers the packaged Material icons in the chat namespace', async () => {
    createFixture([]);
    const registry = TestBed.inject(MatIconRegistry);

    for (const name of ['send', 'retry', 'tts', 'add-file']) {
      const icon = await firstValueFrom(registry.getNamedSvgIcon(name, 'ai-chat'));
      expect(icon.getAttribute('viewBox')).toBe('0 0 24 24');
    }
  });

  it('submits once on Enter and does not emit blank input', () => {
    const fixture = createFixture([]);
    const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;

    textarea.value = '   ';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(emit).not.toHaveBeenCalled();

    textarea.value = 'keyboard message';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

    expect(emit).toHaveBeenCalledOnce();
    expect(emit).toHaveBeenCalledWith('keyboard message');

    textarea.value = 'multiline draft';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }),
    );
    expect(emit).toHaveBeenCalledOnce();
  });

  it('renders replacement host state without retaining submitted messages', () => {
    const fixture = createFixture([]);
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = 'host decides';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.message')).toHaveLength(0);

    fixture.componentRef.setInput('messages', [
      { id: 'replacement', role: 'assistant', text: 'Replacement state' },
    ] satisfies readonly ChatTextMessage[]);
    fixture.detectChanges();

    const messages = fixture.nativeElement.querySelectorAll('.message') as NodeListOf<HTMLElement>;
    expect(messages).toHaveLength(1);
    expect(messages[0].textContent).toContain('Replacement state');
  });
});

function createFixture(messages: readonly ChatTextMessage[]): ComponentFixture<ChatUiComponent> {
  const fixture = TestBed.createComponent(ChatUiComponent);
  fixture.componentRef.setInput('bannerTitle', 'Welcome');
  fixture.componentRef.setInput('bannerDescription', 'Description');
  fixture.componentRef.setInput('messages', messages);
  fixture.detectChanges();
  return fixture;
}
