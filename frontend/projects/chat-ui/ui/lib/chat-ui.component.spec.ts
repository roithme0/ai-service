import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Component, TemplateRef, viewChild } from '@angular/core';
import { By } from '@angular/platform-browser';
import { CdkTextareaAutosize } from '@angular/cdk/text-field';
import { MatIconRegistry } from '@angular/material/icon';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  artifactRenderer,
  type ChatArtifactRenderContext,
  type ChatContent,
  type ChatSubmission,
  type ChatTextMessage,
} from './chat-message';
import { ChatUiComponent } from './chat-ui.component';

const INITIAL_MESSAGES: readonly ChatTextMessage[] = [
  { kind: 'text', id: 'user-1', role: 'user', text: '**literal user text**' },
  { kind: 'text', id: 'assistant-1', role: 'assistant', text: '**formatted assistant text**' },
];

@Component({ template: '<ng-template #template let-payload let-artifact="artifact">Custom: {{ payload.label }} {{ artifact.metadata?.reference }}</ng-template>' })
class RendererTemplateHost {
  readonly template = viewChild.required<
    TemplateRef<ChatArtifactRenderContext<{ readonly label: string }>>
  >(
    'template',
  );
}

describe('ChatUiComponent', () => {
  let originalScrollTo: PropertyDescriptor | undefined;

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    if (originalScrollTo) {
      Object.defineProperty(Element.prototype, 'scrollTo', originalScrollTo);
    } else {
      Reflect.deleteProperty(Element.prototype, 'scrollTo');
    }
  });

  beforeEach(() => {
    originalScrollTo = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTo');
    Object.defineProperty(Element.prototype, 'scrollTo', { configurable: true, value: vi.fn() });
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

  it('renders intermediate Markdown with secondary styling in conversation order', () => {
    const fixture = createFixture([
      { kind: 'intermediate', id: 'update', text: '**Checking** <script>alert(1)</script>' },
      { kind: 'tool', id: 'tool', name: 'check', status: 'completed' },
      { kind: 'text', id: 'final', role: 'assistant', text: 'Standalone result.' },
    ]);
    const element = fixture.nativeElement as HTMLElement;
    const rows = [...element.querySelector('.messages')!.children];
    expect(rows[0].classList.contains('message--intermediate')).toBe(true);
    expect(rows[0].getAttribute('aria-label')).toBe('Zwischenmeldung des Assistenten');
    expect(rows[0].querySelector('strong')?.textContent).toBe('Checking');
    expect(rows[0].querySelector('script')).toBeNull();
    expect(rows[1].classList.contains('tool-call')).toBe(true);
    expect(rows[2].classList.contains('message--assistant')).toBe(true);
  });

  it('renders compact tool rows and artifacts in host order with all four status labels', () => {
    const fixture = createFixture([
      { kind: 'text', id: 'user', role: 'user', text: 'Show' },
      { kind: 'tool', id: 'tool-1', name: '<b>present</b>', status: 'completed' },
      { kind: 'artifact', id: 'artifact', type: 'json', headline: 'Result', payload: { value: 1 } },
      { kind: 'tool', id: 'tool-2', name: 'save', status: 'failed' },
      { kind: 'tool', id: 'tool-3', name: 'update', status: 'outcome_unknown' },
      { kind: 'tool', id: 'tool-4', name: 'check', status: 'not_executed' },
      { kind: 'failure', id: 'failure', text: 'Die Antwort konnte nicht erstellt werden.' },
    ]);
    const element = fixture.nativeElement as HTMLElement;
    expect([...element.querySelector('.messages')!.children].map(child => child.tagName)).toEqual([
      'ARTICLE', 'ARTICLE', 'AI-CHAT-ARTIFACT-CARD', 'ARTICLE', 'ARTICLE', 'ARTICLE', 'ARTICLE',
    ]);
    const rows = [...element.querySelectorAll('.tool-call')];
    expect(rows.map(row => row.querySelector('.tool-call__status')?.textContent?.trim())).toEqual([
      'Abgeschlossen', 'Fehlgeschlagen', 'Ergebnis unklar', 'Nicht ausgeführt',
    ]);
    expect(rows.every(row => row.querySelector('mat-icon')?.getAttribute('svgIcon') === 'ai-chat:tool')).toBe(true);
    expect(rows[0].textContent).toContain('<b>present</b>');
    expect(rows[0].querySelector('b')).toBeNull();
    fixture.componentRef.setInput('conversationStatus', { kind: 'error', placement: 'assistant', message: 'Current failure' });
    fixture.detectChanges();
    expect(element.querySelectorAll('.status--error')).toHaveLength(1);
    fixture.componentRef.setInput('content', [...fixture.componentInstance.content(),
      { kind: 'text', id: 'next-user', role: 'user', text: 'Continue' }]);
    fixture.componentRef.setInput('conversationStatus', null);
    fixture.detectChanges();
    expect(element.querySelectorAll('.status--error')).toHaveLength(1);
  });

  it('uses a matching renderer and renders explicit JSON safely', () => {
    const templateFixture = TestBed.createComponent(RendererTemplateHost);
    templateFixture.detectChanges();
    const content: readonly ChatContent[] = [
      { kind: 'artifact', id: 'custom', type: 'known', headline: 'Known', payload: { label: 'typed' }, metadata: { reference: 'host-action-reference' } },
      { kind: 'artifact', id: 'fallback', type: 'json', headline: 'JSON', payload: { value: {
        nested: [true, null], empty: {}, text: '<script>unsafe()</script>',
      } } },
    ];
    const fixture = createFixture(content);
    fixture.componentRef.setInput('artifactRenderers', {
      known: artifactRenderer(templateFixture.componentInstance.template()),
    });
    fixture.detectChanges();

    const cards = fixture.nativeElement.querySelectorAll('.artifact') as NodeListOf<HTMLElement>;
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Custom: typed');
    expect(cards[0].textContent).toContain('host-action-reference');
    expect(cards[1].querySelector('script')).toBeNull();
    expect(cards[1].querySelector('pre')?.textContent).toContain('"nested"');
    expect(cards[1].textContent).toContain('<script>unsafe()</script>');
  });

  it('does not silently render unsupported types as JSON', () => {
    const fixture = createFixture([{
      kind: 'artifact', id: 'unsupported', type: 'unknown', headline: 'Unknown',
      payload: { secret: 'not presented' },
    }]);
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('pre')).toBeNull();
    expect(element.textContent).toContain('Diese Darstellung wird nicht unterst\u00fctzt.');
    expect(element.textContent).not.toContain('not presented');
  });

  it('renders a subtitle literally beneath the artifact title, outside the collapsible body', () => {
    const fixture = createFixture([
      { kind: 'artifact', id: 'with-subtitle', type: 'json', headline: 'Oats',
        subtitle: '<strong>Example brand</strong>', payload: { value: {} } },
      { kind: 'artifact', id: 'without-subtitle', type: 'json', headline: 'Water', payload: { value: {} } },
    ]);
    const cards = (fixture.nativeElement as HTMLElement).querySelectorAll('.artifact');
    expect(cards[0].querySelector('.artifact-header h3')?.textContent).toBe('Oats');
    expect(cards[0].querySelector('.artifact-header .artifact-subtitle')?.textContent).toBe('<strong>Example brand</strong>');
    expect(cards[0].querySelector('strong')).toBeNull();
    expect(cards[0].querySelector('.artifact-body .artifact-subtitle')).toBeNull();
    expect(cards[1].querySelector('.artifact-subtitle')).toBeNull();
  });

  it('offers library-owned German expansion only for overflowing renderer bodies', async () => {
    class OverflowObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}

      observe(target: Element): void {
        Object.defineProperties(target, {
          scrollHeight: { configurable: true, value: 500 },
          clientHeight: { configurable: true, value: 200 },
        });
        this.callback([], this as unknown as ResizeObserver);
      }

      disconnect(): void {}
      unobserve(): void {}
    }
    vi.stubGlobal('ResizeObserver', OverflowObserver);
    const fixture = createFixture([{
      kind: 'artifact', id: 'large', type: 'json', headline: 'Large', payload: { value: { rows: [1, 2, 3] } },
    }]);
    fixture.detectChanges();
    await fixture.whenStable();

    const toggle = fixture.nativeElement.querySelector('.artifact-toggle') as HTMLButtonElement;
    expect(toggle.textContent).toContain('Mehr anzeigen');
    expect(toggle.querySelector('mat-icon svg path')?.getAttribute('d')).toBe('m6 9 6 6 6-6');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = fixture.nativeElement.querySelector('.artifact-body') as HTMLElement;
    expect(body.classList.contains('artifact-body--faded')).toBe(true);
    toggle.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(toggle.textContent).toContain('Weniger anzeigen');
    expect(toggle.querySelector('mat-icon svg path')?.getAttribute('d')).toBe('m6 15 6-6 6 6');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.classList.contains('artifact-body--faded')).toBe(false);
    expect(fixture.nativeElement.querySelector('.artifact-body--expanded')).not.toBeNull();
  });

  it('retains a submission until the host acknowledges it', () => {
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
    const submission = emit.mock.calls[0][0] as ChatSubmission;
    expect(submission.text).toBe('hello there');
    expect(textarea.value).toBe('  hello there  ');

    submission.acknowledge();
    fixture.detectChanges();

    expect(textarea.value).toBe('');
    expect(fixture.nativeElement.querySelectorAll('.message')).toHaveLength(0);
    expect(document.activeElement).toBe(textarea);
  });

  it('restores composer focus after a disabled interval', () => {
    const fixture = createFixture([]);
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.focus();
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.detectChanges();
    textarea.blur();
    fixture.componentRef.setInput('composerDisabled', false);
    fixture.detectChanges();
    expect(document.activeElement).toBe(textarea);
  });

  it('focuses the composer once when an initially disabled conversation becomes ready', () => {
    const fixture = createFixture([], { disabled: true, focusOnReady: true });
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    expect(document.activeElement).not.toBe(textarea);
    fixture.componentRef.setInput('composerDisabled', false);
    fixture.detectChanges();
    expect(document.activeElement).toBe(textarea);

    textarea.blur();
    fixture.detectChanges();
    expect(document.activeElement).not.toBe(textarea);
  });

  it('preserves focus changes made while initial readiness is pending', () => {
    const fixture = createFixture([], { disabled: true, focusOnReady: true });
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    const other = document.createElement('button');
    document.body.append(other);
    try {
      other.focus();
      other.blur();
      fixture.componentRef.setInput('composerDisabled', false);
      fixture.detectChanges();
      expect(document.activeElement).not.toBe(textarea);
    } finally {
      other.remove();
    }
  });

  it.each([false, true])('preserves another focus target even if it subsequently blurs (%s)', (blur) => {
    const fixture = createFixture([]);
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    const other = document.createElement('button');
    document.body.append(other);
    try {
      textarea.focus();
      fixture.componentRef.setInput('composerDisabled', true);
      fixture.detectChanges();
      other.focus();
      if (blur) other.blur();
      fixture.componentRef.setInput('composerDisabled', false);
      fixture.detectChanges();
      expect(document.activeElement).toBe(blur ? document.body : other);
    } finally {
      other.remove();
    }
  });

  it('does not claim focus when the composer was unfocused before disabling', () => {
    const fixture = createFixture([]);
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    const focus = vi.spyOn(textarea, 'focus');
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.detectChanges();
    fixture.componentRef.setInput('composerDisabled', false);
    fixture.detectChanges();
    expect(focus).not.toHaveBeenCalled();
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

    for (const name of ['send', 'retry', 'tts', 'add-file', 'tool']) {
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
    expect((emit.mock.calls[0][0] as ChatSubmission).text).toBe('keyboard message');

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

    fixture.componentRef.setInput('content', [
      { kind: 'text', id: 'replacement', role: 'assistant', text: 'Replacement state' },
    ] satisfies readonly ChatTextMessage[]);
    fixture.detectChanges();

    const messages = fixture.nativeElement.querySelectorAll('.message') as NodeListOf<HTMLElement>;
    expect(messages).toHaveLength(1);
    expect(messages[0].textContent).toContain('Replacement state');
  });

  it('scrolls history to new messages, statuses, and errors after rendering', () => {
    vi.useFakeTimers();
    const scrollTo = vi.mocked(Element.prototype.scrollTo);
      const fixture = createFixture([]);
      const history = fixture.nativeElement.querySelector('.history') as HTMLElement;
      Object.defineProperty(history, 'scrollHeight', { configurable: true, value: 1000 });
      const scrollToBottom = (): void => {
        expect(scrollTo).toHaveBeenLastCalledWith({ top: 1000, behavior: 'smooth' });
        scrollTo.mockClear();
      };

      fixture.componentRef.setInput('content', [
        { kind: 'text', id: 'user-1', role: 'user', text: 'Hello' },
      ] satisfies readonly ChatTextMessage[]);
      fixture.detectChanges();
      scrollToBottom();

      fixture.componentRef.setInput('conversationStatus', {
        kind: 'loading', message: 'Sending', placement: 'assistant', reveal: 'delayed',
      });
      fixture.detectChanges();
      vi.advanceTimersByTime(300);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.status-content')?.textContent).toContain('Sending');
      scrollToBottom();

      fixture.componentRef.setInput('content', [
        { kind: 'text', id: 'user-1', role: 'user', text: 'Hello' },
        { kind: 'text', id: 'assistant-1', role: 'assistant', text: 'Hi' },
      ] satisfies readonly ChatTextMessage[]);
      fixture.componentRef.setInput('conversationStatus', null);
      fixture.detectChanges();
      scrollToBottom();

      fixture.componentRef.setInput('conversationStatus', {
        kind: 'error', message: 'Failed', placement: 'assistant',
      });
      fixture.detectChanges();
      scrollToBottom();
  });

  it('reveals a slow sending label after 300 ms and replaces it immediately', () => {
    vi.useFakeTimers();
    const fixture = createFixture([]);
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading', message: 'Sending', placement: 'assistant', reveal: 'delayed',
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status--delayed')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.status-content')).toBeNull();
    expect((fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement).disabled).toBe(true);
    vi.advanceTimersByTime(299);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status-content')).toBeNull();
    vi.advanceTimersByTime(1);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status-content--fade')?.textContent).toContain('Sending');
    const sendingLabel = fixture.nativeElement.querySelector('.status-content');
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading', message: 'Generating', placement: 'assistant',
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status')?.textContent).toContain('Generating');
    const generatingLabel = fixture.nativeElement.querySelector('.status-content');
    expect(generatingLabel.classList.contains('status-content--fade')).toBe(true);
    expect(generatingLabel).not.toBe(sendingLabel);
  });

  it('cancels a quick sending reveal and starts a fresh delay for the next send', () => {
    vi.useFakeTimers();
    const fixture = createFixture([]);
    const sending = { kind: 'loading', message: 'Sending', placement: 'assistant', reveal: 'delayed' } as const;
    fixture.componentRef.setInput('conversationStatus', sending);
    fixture.detectChanges();
    vi.advanceTimersByTime(100);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error', message: 'Failed', placement: 'assistant',
    });
    fixture.detectChanges();
    vi.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status')?.textContent).toContain('Failed');
    fixture.componentRef.setInput('conversationStatus', sending);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status-content')).toBeNull();
    vi.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.status')?.textContent).toContain('Sending');
    fixture.destroy();
  });

  it('disables submission and renders host-controlled loading and recovery states', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Antwort wird erstellt …',
      placement: 'assistant',
    });
    fixture.detectChanges();

    expect((fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement).disabled).toBe(
      true,
    );
    expect(fixture.nativeElement.querySelector('.status')?.textContent).toContain(
      'Antwort wird erstellt …',
    );

    const actionEmit = vi.spyOn(fixture.componentInstance.statusActionTriggered, 'emit');
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error',
      message: 'Das Modell ist nicht verfügbar.',
      placement: 'assistant',
      action: { id: 'retry-turn', label: 'Erneut versuchen' },
    });
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('.status-action') as HTMLButtonElement).click();

    expect(actionEmit).toHaveBeenCalledWith('retry-turn');
    expect(fixture.nativeElement.querySelector('.status-content').classList.contains('status-content--fade')).toBe(false);
  });
});

function createFixture(
  messages: readonly ChatContent[],
  options: { disabled?: boolean; focusOnReady?: boolean } = {},
): ComponentFixture<ChatUiComponent> {
  const fixture = TestBed.createComponent(ChatUiComponent);
  fixture.componentRef.setInput('bannerTitle', 'Welcome');
  fixture.componentRef.setInput('bannerDescription', 'Description');
  fixture.componentRef.setInput('content', messages);
  fixture.componentRef.setInput('composerDisabled', options.disabled ?? false);
  fixture.componentRef.setInput('focusOnReady', options.focusOnReady ?? false);
  fixture.detectChanges();
  return fixture;
}
