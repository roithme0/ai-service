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

@Component({ template: '<ng-template #template let-payload>Custom: {{ payload.label }}</ng-template>' })
class RendererTemplateHost {
  readonly template = viewChild.required<
    TemplateRef<ChatArtifactRenderContext<{ readonly label: string }>>
  >(
    'template',
  );
}

describe('ChatUiComponent', () => {
  afterEach(() => vi.unstubAllGlobals());

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

  it('uses a matching renderer and safely falls back to readable JSON', () => {
    const templateFixture = TestBed.createComponent(RendererTemplateHost);
    templateFixture.detectChanges();
    const content: readonly ChatContent[] = [
      { kind: 'artifact', id: 'custom', type: 'known', headline: 'Known', payload: { label: 'typed' } },
      { kind: 'artifact', id: 'fallback', type: 'unknown', headline: 'Unknown', payload: {
        nested: [true, null], empty: {}, text: '<script>unsafe()</script>',
      } },
    ];
    const fixture = createFixture(content);
    fixture.componentRef.setInput('artifactRenderers', {
      known: artifactRenderer(templateFixture.componentInstance.template()),
    });
    fixture.detectChanges();

    const cards = fixture.nativeElement.querySelectorAll('.artifact') as NodeListOf<HTMLElement>;
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('Custom: typed');
    expect(cards[1].querySelector('script')).toBeNull();
    expect(cards[1].querySelector('pre')?.textContent).toContain('"nested"');
    expect(cards[1].textContent).toContain('<script>unsafe()</script>');
  });

  it('offers library-owned German expansion only for overflowing renderer bodies', () => {
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
      kind: 'artifact', id: 'large', type: 'unknown', headline: 'Large', payload: { rows: [1, 2, 3] },
    }]);
    fixture.detectChanges();

    const toggle = fixture.nativeElement.querySelector('.artifact-toggle') as HTMLButtonElement;
    expect(toggle.textContent).toContain('Mehr anzeigen');
    toggle.click();
    fixture.detectChanges();
    expect(toggle.textContent).toContain('Weniger anzeigen');
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
  });
});

function createFixture(messages: readonly ChatContent[]): ComponentFixture<ChatUiComponent> {
  const fixture = TestBed.createComponent(ChatUiComponent);
  fixture.componentRef.setInput('bannerTitle', 'Welcome');
  fixture.componentRef.setInput('bannerDescription', 'Description');
  fixture.componentRef.setInput('content', messages);
  fixture.detectChanges();
  return fixture;
}
