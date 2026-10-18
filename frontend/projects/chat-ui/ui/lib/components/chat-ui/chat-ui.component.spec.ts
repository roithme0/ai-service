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
  type ChatTextMessage,
  type ChatTurn,
} from '../../models/chat-message';
import { ChatUiComponent } from './chat-ui.component';

const INITIAL_MESSAGES: readonly ChatTextMessage[] = [
  { kind: 'text', isFinal: false, id: 'user-1', role: 'user', text: '**literal user text**' },
  {
    kind: 'text',
    isFinal: false,
    id: 'assistant-1',
    role: 'assistant',
    text: '**formatted assistant text**',
  },
];

const DISCLOSURE_CONTENT: readonly ChatContent[] = [
  { kind: 'text', isFinal: false, id: 'request', role: 'user', text: 'Request' },
  { kind: 'intermediate', id: 'detail', text: 'Checking' },
  { kind: 'tool', id: 'recoverable', name: 'check', status: 'failed' },
  { kind: 'text', isFinal: true, id: 'answer', role: 'assistant', text: 'Answer' },
];

@Component({
  template:
    '<ng-template #template let-payload let-artifact="artifact">Custom: {{ payload.label }} {{ artifact.metadata?.reference }}</ng-template>',
})
class RendererTemplateHost {
  readonly template =
    viewChild.required<TemplateRef<ChatArtifactRenderContext<{ readonly label: string }>>>(
      'template',
    );
}

describe('ChatUiComponent', () => {
  const scrollTo = vi.fn<Element['scrollTo']>();
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
    scrollTo.mockClear();
    originalScrollTo = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTo');
    Object.defineProperty(Element.prototype, 'scrollTo', { configurable: true, value: scrollTo });
    TestBed.configureTestingModule({ imports: [ChatUiComponent] });
  });

  it('collapses details only after completion and places an accessible toggle below the explicit answer', () => {
    const fixture = createFixture([]);
    const turn: ChatTurn = {
      id: 'first',
      userMessageId: 'request',
      status: 'active',
      content: DISCLOSURE_CONTENT,
    };
    fixture.componentRef.setInput('turns', [turn]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const detail = element.querySelector<HTMLElement>('.message--intermediate')!;
    expect(detail.hidden).toBe(false);
    expect(element.querySelector('.details-toggle')).toBeNull();

    fixture.componentRef.setInput('turns', [{ ...turn, status: 'completed' }]);
    fixture.detectChanges();
    expect(detail.hidden).toBe(true);
    expect(element.querySelector<HTMLElement>('ai-chat-tool-call')!.hidden).toBe(true);
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    expect(toggle.type).toBe('button');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-label')).toBe('Details anzeigen');
    expect(toggle.querySelector('mat-icon')?.getAttribute('svgIcon')).toBe('ai-chat:list-tree');
    expect(toggle.parentElement?.previousElementSibling?.textContent).toContain('Answer');
    toggle.click();
    fixture.detectChanges();
    expect(detail.hidden).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.getAttribute('aria-label')).toBe('Details ausblenden');
  });

  it.each(['failed', 'unknown'] as const)(
    'keeps details visible for a %s turn even with explicit final text',
    (status) => {
      const fixture = createFixture([]);
      fixture.componentRef.setInput('turns', [
        { id: 'first', userMessageId: 'request', status, content: DISCLOSURE_CONTENT },
      ]);
      fixture.detectChanges();
      const element = fixtureElement(fixture);
      expect(element.querySelector<HTMLElement>('.message--intermediate')!.hidden).toBe(false);
      expect(element.querySelector<HTMLElement>('ai-chat-tool-call')!.hidden).toBe(false);
      expect(element.querySelector('.details-toggle')).toBeNull();
    },
  );

  it.each([
    { content: [] },
    {
      content: DISCLOSURE_CONTENT.filter(
        (item) => item.kind !== 'tool' && item.kind !== 'intermediate',
      ),
    },
    { content: DISCLOSURE_CONTENT.filter((item) => item.kind !== 'text' || !item.isFinal) },
  ])(
    'does not offer disclosure without both details and an explicit final answer (%j)',
    ({ content }) => {
      const fixture = createFixture(content);
      expect(fixtureElement(fixture).querySelector('.details-toggle')).toBeNull();
      expect(fixtureElement(fixture).querySelector('[hidden]')).toBeNull();
    },
  );

  it('uses the first explicitly final answer rather than later unspecified or additional final text', () => {
    const fixture = createFixture([
      ...DISCLOSURE_CONTENT,
      {
        kind: 'text',
        isFinal: true,
        id: 'another-final',
        role: 'assistant',
        text: 'Another final',
      },
      { kind: 'text', isFinal: false, id: 'later', role: 'assistant', text: 'Later ordinary text' },
      { kind: 'failure', id: 'failure', text: 'Retained failure' },
    ]);
    const element = fixtureElement(fixture);
    expect(element.querySelectorAll('.details-toggle')).toHaveLength(1);
    expect(element.querySelector('.answer-actions')?.previousElementSibling?.textContent).toBe(
      'Answer',
    );
    const visibleText = [...element.querySelectorAll<HTMLElement>('article:not([hidden])')].map(
      (item) => item.textContent,
    );
    expect(visibleText).toEqual([
      'Request',
      'Answer',
      'Another final',
      'Later ordinary text',
      'Retained failure',
    ]);
  });

  it('remembers manual disclosure per historical turn across new inputs and resets on recreation', () => {
    const fixture = createFixture(DISCLOSURE_CONTENT);
    const element = fixtureElement(fixture);
    element.querySelector<HTMLButtonElement>('.details-toggle')!.click();
    fixture.detectChanges();
    const historical = fixture.componentInstance.turns()[0];
    const next: ChatTurn = { ...historical, id: 'next', content: [...DISCLOSURE_CONTENT] };
    fixture.componentRef.setInput('turns', [
      { ...historical, content: [...historical.content] },
      next,
    ]);
    fixture.detectChanges();
    const toggles = element.querySelectorAll<HTMLButtonElement>('.details-toggle');
    expect([...toggles].map((toggle) => toggle.getAttribute('aria-expanded'))).toEqual([
      'true',
      'false',
    ]);
    toggles[0].click();
    fixture.detectChanges();
    fixture.componentRef.setInput('turns', [
      ...fixture.componentInstance.turns(),
      { id: 'pending', userMessageId: 'pending-user', status: 'active', content: [] },
    ]);
    fixture.detectChanges();
    expect(toggles[0].getAttribute('aria-expanded')).toBe('false');
    toggles[1].click();
    fixture.detectChanges();
    expect(toggles[1].getAttribute('aria-expanded')).toBe('true');
    fixture.destroy();
    const recreated = createFixture(DISCLOSURE_CONTENT);
    expect(
      fixtureElement(recreated).querySelector('.details-toggle')?.getAttribute('aria-expanded'),
    ).toBe('false');
  });

  it('preserves interleaved artifact nodes, renderer DOM state and order across toggles', () => {
    const templateFixture = TestBed.createComponent(RendererTemplateHost);
    templateFixture.detectChanges();
    const fixture = createFixture([
      DISCLOSURE_CONTENT[0],
      DISCLOSURE_CONTENT[1],
      {
        kind: 'artifact',
        id: 'card',
        type: 'known',
        headline: 'Card',
        payload: { label: 'retained' },
      },
      DISCLOSURE_CONTENT[2],
      DISCLOSURE_CONTENT[3],
    ]);
    fixture.componentRef.setInput('artifactRenderers', {
      known: artifactRenderer(templateFixture.componentInstance.template()),
    });
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const card = element.querySelector('ai-chat-artifact-card')!;
    const rendererBody = card.querySelector('.artifact-body')!;
    const localInput = document.createElement('input');
    localInput.value = 'renderer local state';
    rendererBody.append(localInput);
    const rows = [...element.querySelector('.messages')!.children];
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    for (let index = 0; index < 2; index++) {
      toggle.click();
      fixture.detectChanges();
      expect(element.querySelector('ai-chat-artifact-card')).toBe(card);
      expect(card.querySelector('.artifact-body')).toBe(rendererBody);
      expect(card.querySelector('input')?.value).toBe('renderer local state');
      expect([...element.querySelector('.messages')!.children]).toEqual(rows);
    }
  });

  it('expands before scrolling the first timeline item to the viewport top and preserves collapse offset', () => {
    const fixture = createFixture(DISCLOSURE_CONTENT);
    const element = fixtureElement(fixture);
    const history = element.querySelector<HTMLElement>('.history')!;
    const anchor = element.querySelector<HTMLElement>('[data-turn-start]')!;
    const detail = element.querySelector<HTMLElement>('.message--intermediate')!;
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    Object.defineProperties(history, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 400 },
      clientTop: { configurable: true, value: 2 },
    });
    history.scrollTop = 300;
    vi.spyOn(history, 'getBoundingClientRect').mockReturnValue({ top: 50 } as DOMRect);
    vi.spyOn(anchor, 'getBoundingClientRect').mockImplementation(() => {
      expect(detail.hidden).toBe(false);
      return { top: 202 } as DOMRect;
    });
    scrollTo.mockClear();
    toggle.click();
    fixture.detectChanges();
    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ top: 450, behavior: 'smooth' });
    scrollTo.mockClear();

    history.scrollTop = 600;
    toggle.click();
    history.scrollTop = 450;
    fixture.detectChanges();
    expect(history.scrollTop).toBe(600);
    expect(scrollTo).not.toHaveBeenCalled();

    toggle.click();
    fixture.detectChanges();
    scrollTo.mockClear();
    history.scrollTop = 1800;
    toggle.click();
    fixture.detectChanges();
    expect(history.scrollTop).toBe(1600);
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('renders ordered host messages and applies Markdown only to assistant text', () => {
    const fixture = createFixture(INITIAL_MESSAGES);
    const messageElements = fixtureElement(fixture).querySelectorAll<HTMLElement>('.message');

    expect(messageElements).toHaveLength(2);
    expect(messageElements[0].classList.contains('message--user')).toBe(true);
    expect(messageElements[0].textContent).toContain('**literal user text**');
    expect(messageElements[0].querySelector('strong')).toBeNull();
    expect(messageElements[1].classList.contains('message--assistant')).toBe(true);
    expect(messageElements[1].querySelector('strong')?.textContent).toBe(
      'formatted assistant text',
    );
  });

  it('renders turn-owned content in order and preserves historical failures with a current error', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', [
      {
        id: 'first',
        userMessageId: 'first-user',
        status: 'failed',
        content: [
          { kind: 'text', isFinal: false, id: 'first-user', role: 'user', text: 'First' },
          { kind: 'failure', id: 'first-failure', text: 'Historical failure' },
        ],
      },
      {
        id: 'second',
        userMessageId: 'second-user',
        status: 'failed',
        content: [
          { kind: 'text', isFinal: false, id: 'second-user', role: 'user', text: 'Second' },
          { kind: 'intermediate', id: 'detail', text: 'Checking' },
          { kind: 'tool', id: 'tool', name: 'check', status: 'failed' },
          {
            kind: 'artifact',
            id: 'result',
            type: 'json',
            headline: 'Result',
            payload: { value: 1 },
          },
          { kind: 'failure', id: 'second-failure', text: 'Covered failure' },
        ],
      },
    ]);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error',
      placement: 'assistant',
      message: 'Current error',
    });
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const rows = [...element.querySelector('.messages')!.children];
    expect(rows.map((row) => row.tagName)).toEqual([
      'ARTICLE',
      'ARTICLE',
      'ARTICLE',
      'ARTICLE',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-ARTIFACT-CARD',
      'ARTICLE',
    ]);
    expect(rows[0].textContent).toContain('First');
    expect(rows[1].textContent).toContain('Historical failure');
    expect(rows[2].textContent).toContain('Second');
    expect(rows[3].textContent).toContain('Checking');
    expect(rows[4].textContent).toContain('check');
    expect(rows[6].textContent).toContain('Current error');
    expect(element.textContent).not.toContain('Covered failure');
  });

  it('renders safe intermediate Markdown in conversation order', () => {
    const fixture = createFixture([
      { kind: 'intermediate', id: 'update', text: '**Checking** <script>alert(1)</script>' },
      { kind: 'tool', id: 'tool', name: 'check', status: 'completed' },
      { kind: 'text', isFinal: true, id: 'final', role: 'assistant', text: 'Standalone result.' },
    ]);
    const element = fixtureElement(fixture);
    const rows = [...element.querySelector('.messages')!.children];
    expect(rows[0].classList.contains('message--intermediate')).toBe(true);
    expect(rows[0].getAttribute('aria-label')).toBe('Zwischenmeldung des Assistenten');
    expect(rows[0].querySelector('strong')?.textContent).toBe('Checking');
    expect(rows[0].querySelector('script')).toBeNull();
    expect(rows[1].matches('ai-chat-tool-call')).toBe(true);
    expect(rows[2].classList.contains('message--assistant')).toBe(true);
  });

  it('renders compact tool rows and artifacts in host order with all four status labels', () => {
    const fixture = createFixture([
      { kind: 'text', isFinal: false, id: 'user', role: 'user', text: 'Show' },
      { kind: 'tool', id: 'tool-1', name: '<b>present</b>', status: 'completed' },
      { kind: 'artifact', id: 'artifact', type: 'json', headline: 'Result', payload: { value: 1 } },
      { kind: 'tool', id: 'tool-2', name: 'save', status: 'failed' },
      { kind: 'tool', id: 'tool-3', name: 'update', status: 'outcome_unknown' },
      { kind: 'tool', id: 'tool-4', name: 'check', status: 'not_executed' },
      { kind: 'failure', id: 'failure', text: 'Die Antwort konnte nicht erstellt werden.' },
    ]);
    const element = fixtureElement(fixture);
    expect([...element.querySelector('.messages')!.children].map((child) => child.tagName)).toEqual(
      [
        'ARTICLE',
        'AI-CHAT-TOOL-CALL',
        'AI-CHAT-ARTIFACT-CARD',
        'AI-CHAT-TOOL-CALL',
        'AI-CHAT-TOOL-CALL',
        'AI-CHAT-TOOL-CALL',
        'ARTICLE',
      ],
    );
    const rows = [...element.querySelectorAll('ai-chat-tool-call')];
    expect(rows.map((row) => row.querySelector('.status')?.textContent?.trim())).toEqual([
      'Abgeschlossen',
      'Fehlgeschlagen',
      'Ergebnis unklar',
      'Nicht ausgeführt',
    ]);
    expect(
      rows.every(
        (row) => row.querySelector('mat-icon')?.getAttribute('svgIcon') === 'ai-chat:tool',
      ),
    ).toBe(true);
    expect(rows[0].textContent).toContain('<b>present</b>');
    expect(rows[0].querySelector('b')).toBeNull();
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error',
      placement: 'assistant',
      message: 'Current failure',
    });
    fixture.detectChanges();
    expect(element.querySelectorAll('.status--error')).toHaveLength(1);
    setContent(fixture, [
      ...fixture.componentInstance.turns()[0].content,
      { kind: 'text', isFinal: false, id: 'next-user', role: 'user', text: 'Continue' },
    ]);
    fixture.componentRef.setInput('conversationStatus', null);
    fixture.detectChanges();
    expect(element.querySelectorAll('.status--error')).toHaveLength(1);
  });

  it('uses a matching renderer and renders explicit JSON safely', () => {
    const templateFixture = TestBed.createComponent(RendererTemplateHost);
    templateFixture.detectChanges();
    const content: readonly ChatContent[] = [
      {
        kind: 'artifact',
        id: 'custom',
        type: 'known',
        headline: 'Known',
        payload: { label: 'typed' },
        metadata: { reference: 'host-action-reference' },
      },
      {
        kind: 'artifact',
        id: 'fallback',
        type: 'json',
        headline: 'JSON',
        payload: {
          value: {
            nested: [true, null],
            empty: {},
            text: '<script>unsafe()</script>',
          },
        },
      },
    ];
    const fixture = createFixture(content);
    fixture.componentRef.setInput('artifactRenderers', {
      known: artifactRenderer(templateFixture.componentInstance.template()),
    });
    fixture.detectChanges();

    const cards = fixtureElement(fixture).querySelectorAll<HTMLElement>('.artifact');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Custom: typed');
    expect(cards[0].textContent).toContain('host-action-reference');
    expect(cards[1].querySelector('script')).toBeNull();
    expect(cards[1].querySelector('pre')?.textContent).toContain('"nested"');
    expect(cards[1].textContent).toContain('<script>unsafe()</script>');
  });

  it('does not silently render unsupported types as JSON', () => {
    const fixture = createFixture([
      {
        kind: 'artifact',
        id: 'unsupported',
        type: 'unknown',
        headline: 'Unknown',
        payload: { secret: 'not presented' },
      },
    ]);
    const element = fixtureElement(fixture);
    expect(element.querySelector('pre')).toBeNull();
    expect(element.textContent).toContain('Diese Darstellung wird nicht unterst\u00fctzt.');
    expect(element.textContent).not.toContain('not presented');
  });

  it('renders a subtitle literally beneath the artifact title, outside the collapsible body', () => {
    const fixture = createFixture([
      {
        kind: 'artifact',
        id: 'with-subtitle',
        type: 'json',
        headline: 'Oats',
        subtitle: '<strong>Example brand</strong>',
        payload: { value: {} },
      },
      {
        kind: 'artifact',
        id: 'without-subtitle',
        type: 'json',
        headline: 'Water',
        payload: { value: {} },
      },
    ]);
    const cards = fixtureElement(fixture).querySelectorAll('.artifact');
    expect(cards[0].querySelector('.artifact-header h3')?.textContent).toBe('Oats');
    expect(cards[0].querySelector('.artifact-header .artifact-subtitle')?.textContent).toBe(
      '<strong>Example brand</strong>',
    );
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
        this.callback([], this);
      }

      disconnect(): void {}
      unobserve(): void {}
    }
    vi.stubGlobal('ResizeObserver', OverflowObserver);
    const fixture = createFixture([
      {
        kind: 'artifact',
        id: 'large',
        type: 'json',
        headline: 'Large',
        payload: { value: { rows: [1, 2, 3] } },
      },
    ]);
    fixture.detectChanges();
    await fixture.whenStable();

    const toggle = fixtureElement(fixture).querySelector('.artifact-toggle') as HTMLButtonElement;
    expect(toggle.textContent).toContain('Mehr anzeigen');
    expect(toggle.querySelector('mat-icon svg path')?.getAttribute('d')).toBe('m6 9 6 6 6-6');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = fixtureElement(fixture).querySelector('.artifact-body') as HTMLElement;
    expect(body.classList.contains('artifact-body--faded')).toBe(true);
    toggle.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(toggle.textContent).toContain('Weniger anzeigen');
    expect(toggle.querySelector('mat-icon svg path')?.getAttribute('d')).toBe('m6 15 6-6 6 6');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.classList.contains('artifact-body--faded')).toBe(false);
    expect(fixtureElement(fixture).querySelector('.artifact-body--expanded')).not.toBeNull();
  });

  it('retains a submission until the host acknowledges it', () => {
    const fixture = createFixture([]);
    const component = fixture.componentInstance;
    const emit = vi.spyOn(component.messageSubmitted, 'emit');
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;

    textarea.value = '  hello there  ';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    (fixtureElement(fixture).querySelector('button') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(emit).toHaveBeenCalledOnce();
    const submission = emit.mock.calls[0][0];
    expect(submission.text).toBe('hello there');
    expect(textarea.value).toBe('  hello there  ');

    submission.acknowledge();
    fixture.detectChanges();

    expect(textarea.value).toBe('');
    expect(fixtureElement(fixture).querySelectorAll('.message')).toHaveLength(0);
    expect(document.activeElement).toBe(textarea);
  });

  it('restores composer focus after a disabled interval', () => {
    const fixture = createFixture([]);
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
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
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
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
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
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

  it.each([false, true])(
    'preserves another focus target even if it subsequently blurs (%s)',
    (blur) => {
      const fixture = createFixture([]);
      const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
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
    },
  );

  it('does not claim focus when the composer was unfocused before disabling', () => {
    const fixture = createFixture([]);
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
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
    const button = fixtureElement(fixture).querySelector('button[matIconButton]');
    const icon = fixtureElement(fixture).querySelector('mat-icon[svgIcon="ai-chat:send"]');

    expect(button).not.toBeNull();
    expect(icon).not.toBeNull();
  });

  it('renders only the send action inside the composer surface', () => {
    const fixture = createFixture([]);
    const surface = fixtureElement(fixture).querySelector('.surface') as HTMLElement;
    const actions = surface.querySelector('.actions') as HTMLElement;

    expect(surface.querySelector('textarea')).not.toBeNull();
    expect(actions.querySelectorAll('button')).toHaveLength(1);
    expect(actions.querySelector('.send-button')).not.toBeNull();
  });

  it('registers the packaged icons in the chat namespace', async () => {
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
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;

    textarea.value = '   ';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(emit).not.toHaveBeenCalled();

    textarea.value = 'keyboard message';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

    expect(emit).toHaveBeenCalledOnce();
    expect(emit.mock.calls[0][0].text).toBe('keyboard message');

    textarea.value = 'multiline draft';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }),
    );
    expect(emit).toHaveBeenCalledOnce();
  });

  it('renders replacement host state without retaining submitted messages', () => {
    const fixture = createFixture([]);
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = 'host decides';
    textarea.dispatchEvent(new Event('input'));
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelectorAll('.message')).toHaveLength(0);

    setContent(fixture, [
      {
        kind: 'text',
        isFinal: false,
        id: 'replacement',
        role: 'assistant',
        text: 'Replacement state',
      },
    ] satisfies readonly ChatTextMessage[]);
    fixture.detectChanges();

    const messages = fixtureElement(fixture).querySelectorAll<HTMLElement>('.message');
    expect(messages).toHaveLength(1);
    expect(messages[0].textContent).toContain('Replacement state');
  });

  it('scrolls history to new messages, statuses, and errors after rendering', () => {
    vi.useFakeTimers();
    const fixture = createFixture([]);
    const history = fixtureElement(fixture).querySelector('.history') as HTMLElement;
    Object.defineProperty(history, 'scrollHeight', { configurable: true, value: 1000 });
    const scrollToBottom = (): void => {
      expect(scrollTo).toHaveBeenLastCalledWith({ top: 1000, behavior: 'smooth' });
      scrollTo.mockClear();
    };

    setContent(fixture, [
      { kind: 'text', isFinal: false, id: 'user-1', role: 'user', text: 'Hello' },
    ] satisfies readonly ChatTextMessage[]);
    fixture.detectChanges();
    scrollToBottom();

    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Sending',
      placement: 'assistant',
      reveal: 'delayed',
    });
    fixture.detectChanges();
    vi.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Sending',
    );
    scrollToBottom();

    setContent(fixture, [
      { kind: 'text', isFinal: false, id: 'user-1', role: 'user', text: 'Hello' },
      { kind: 'text', isFinal: false, id: 'assistant-1', role: 'assistant', text: 'Hi' },
    ] satisfies readonly ChatTextMessage[]);
    fixture.componentRef.setInput('conversationStatus', null);
    fixture.detectChanges();
    scrollToBottom();

    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error',
      message: 'Failed',
      placement: 'assistant',
    });
    fixture.detectChanges();
    scrollToBottom();
  });

  it('reveals accessible sending dots after 300 ms and updates their label immediately', () => {
    vi.useFakeTimers();
    const fixture = createFixture([]);
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Sending',
      placement: 'assistant',
      reveal: 'delayed',
    });
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.status--delayed')).not.toBeNull();
    expect(fixtureElement(fixture).querySelector('.status-content')).toBeNull();
    expect(
      (fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement).disabled,
    ).toBe(true);
    vi.advanceTimersByTime(299);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.status-content')).toBeNull();
    vi.advanceTimersByTime(1);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Sending',
    );
    expect(fixtureElement(fixture).querySelector('.status p')).toBeNull();
    const sendingLabel = fixtureElement(fixture).querySelector('.status-content');
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Generating',
      placement: 'assistant',
    });
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Generating',
    );
    const generatingLabel = fixtureElement(fixture).querySelector('.status-content');
    expect(generatingLabel!.classList.contains('status-content--fade')).toBe(false);
    expect(generatingLabel).not.toBe(sendingLabel);
  });

  it('cancels a quick sending reveal and starts a fresh delay for the next send', () => {
    vi.useFakeTimers();
    const fixture = createFixture([]);
    const sending = {
      kind: 'loading',
      message: 'Sending',
      placement: 'assistant',
      reveal: 'delayed',
    } as const;
    fixture.componentRef.setInput('conversationStatus', sending);
    fixture.detectChanges();
    vi.advanceTimersByTime(100);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'error',
      message: 'Failed',
      placement: 'assistant',
    });
    fixture.detectChanges();
    vi.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.status')?.textContent).toContain('Failed');
    fixture.componentRef.setInput('conversationStatus', sending);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.status-content')).toBeNull();
    vi.advanceTimersByTime(300);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Sending',
    );
    fixture.destroy();
  });

  it('keeps conversation startup as text without response dots', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Starting conversation',
      placement: 'conversation',
    });
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')).toBeNull();
    expect(fixtureElement(fixture).querySelector('.status p')?.textContent).toBe(
      'Starting conversation',
    );
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

    expect(
      (fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement).disabled,
    ).toBe(true);
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
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
    (fixtureElement(fixture).querySelector('.status-action') as HTMLButtonElement).click();

    expect(actionEmit).toHaveBeenCalledWith('retry-turn');
    expect(
      fixtureElement(fixture)
        .querySelector('.status-content')!
        .classList.contains('status-content--fade'),
    ).toBe(false);
  });
});

function createFixture(
  messages: readonly ChatContent[],
  options: { disabled?: boolean; focusOnReady?: boolean } = {},
): ComponentFixture<ChatUiComponent> {
  const fixture = TestBed.createComponent(ChatUiComponent);
  fixture.componentRef.setInput('bannerTitle', 'Welcome');
  fixture.componentRef.setInput('bannerDescription', 'Description');
  setContent(fixture, messages);
  fixture.componentRef.setInput('composerDisabled', options.disabled ?? false);
  fixture.componentRef.setInput('focusOnReady', options.focusOnReady ?? false);
  fixture.detectChanges();
  return fixture;
}

function fixtureElement<T>(fixture: ComponentFixture<T>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

function setContent(
  fixture: ComponentFixture<ChatUiComponent>,
  content: readonly ChatContent[],
): void {
  fixture.componentRef.setInput(
    'turns',
    content.length === 0
      ? []
      : [{ id: 'turn-1', userMessageId: 'user-1', status: 'completed', content }],
  );
}
