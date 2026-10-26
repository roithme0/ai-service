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
import { ArtifactCardComponent } from '../artifact-card/artifact-card.component';
import { ChatUiComponent } from './chat-ui.component';
import { presentSession } from '../../../../conversation/src/session-presentation';
import type { PresentedSession, PresentedTurn } from '../../../../conversation/generated/types.gen';
import type { ChatUsage } from '../../models/chat-usage';

const EMPTY_CHAT_USAGE: ChatUsage = {
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

const EMPTY_USAGE: PresentedSession['usage'] = {
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
  reasoning_tokens: 0,
  requests: 0,
  tool_calls: 0,
  estimated_cost_usd: null,
};

const INITIAL_MESSAGES: readonly ChatTextMessage[] = [
  {
    kind: 'text',
    isFinal: false,
    id: 'user-1',
    role: 'user',
    text: '**literal user text** <img src=x>\nNext line',
  },
  {
    kind: 'text',
    isFinal: false,
    id: 'assistant-1',
    role: 'assistant',
    text: '**formatted assistant text**',
  },
];

const FOCUS_CONTROLS = ['.send-button', '.details-toggle', '.artifact-toggle'] as const;

const DETAILS_CONTENT: readonly ChatContent[] = [
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

  it('renders optional usage inside the composer and removes it without changing the mascot', () => {
    const fixture = createFixture([]);
    const root = fixtureElement(fixture);
    const mascot = root.querySelector('.mascot');
    expect(root.querySelector('ai-chat-usage-line')).toBeNull();

    fixture.componentRef.setInput('usage', {
      ...EMPTY_CHAT_USAGE,
      totalTokens: 12800,
      estimatedCostUsd: '0.02400000000000000001',
    });
    fixture.detectChanges();
    const line = root.querySelector('ai-chat-composer ai-chat-usage-line')!;
    expect(line.textContent).toContain('Geschätzt $0.024');
    expect(line.textContent).toContain('12.8K Tokens');
    expect(line.querySelector('[title]')?.getAttribute('title')).toContain(
      '0.02400000000000000001 USD; 12800 Tokens',
    );
    expect(line.querySelector('button')).toBeNull();
    expect(root.querySelector('.mascot')).toBe(mascot);

    fixture.componentRef.setInput('usage', null);
    fixture.detectChanges();
    expect(root.querySelector('ai-chat-usage-line')).toBeNull();
    expect(root.querySelector('.mascot')).toBe(mascot);
  });

  it.each([
    { cost: null, expected: 'Kosten unbekannt' },
    { cost: '0', expected: 'Geschätzt $0' },
    { cost: '0.00000012', expected: 'Geschätzt $0.00000012' },
  ])('updates usage while preserving the meaning of cost $cost', ({ cost, expected }) => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('usage', {
      ...EMPTY_CHAT_USAGE,
      totalTokens: 1,
      estimatedCostUsd: '1',
    });
    fixture.detectChanges();
    fixture.componentRef.setInput('usage', {
      ...EMPTY_CHAT_USAGE,
      totalTokens: 0,
      estimatedCostUsd: cost,
    });
    fixture.detectChanges();
    const line = fixtureElement(fixture).querySelector('ai-chat-usage-line')!;
    expect(line.textContent).toContain(expected);
    expect(line.textContent).toContain('0 Tokens');
  });

  it('toggles the usage panel without submitting, losing the draft, or moving pointer focus', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('usage', {
      ...EMPTY_CHAT_USAGE,
      inputTokens: 9600,
      outputTokens: 3200,
      totalTokens: 12800,
      reasoningTokens: 1240,
      cacheReadTokens: 6400,
      cacheWriteTokens: 800,
      toolCalls: 4,
      requests: 8,
      estimatedCostUsd: '0.024',
    });
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.detectChanges();
    const root = fixtureElement(fixture);
    const textarea = root.querySelector('textarea')!;
    textarea.value = 'Keep this draft';
    textarea.dispatchEvent(new Event('input'));
    textarea.focus();
    const submitted = vi.fn();
    fixture.componentInstance.messageSubmitted.subscribe(submitted);
    const expand = root.querySelector<HTMLButtonElement>('.usage-toggle')!;
    const panel = root.querySelector<HTMLElement>('.usage-panel')!;
    const line = root.querySelector<HTMLElement>('.usage-line')!;
    expect(panel.inert).toBe(true);
    expand.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
    fixture.detectChanges();
    expect(panel.inert).toBe(false);
    expect(panel.classList.contains('expanded')).toBe(true);
    expect(line.inert).toBe(true);
    expect(root.querySelector('.mascot')?.classList.contains('faded')).toBe(true);
    expect(Array.from(panel.querySelectorAll('dd'), (item) => item.textContent?.trim())).toEqual([
      '9.6K',
      '3.2K',
      '1.2K',
      '12.8K',
      '6.4K',
      '800',
      '4',
      '8',
    ]);
    expect(panel.querySelectorAll('dd')[2].getAttribute('title')).toBe('1240');
    expect(panel.querySelector('.cost')?.textContent).toContain('$0.024');
    expect(document.activeElement).toBe(textarea);
    expect(textarea.value).toBe('Keep this draft');
    expect(submitted).not.toHaveBeenCalled();

    fixture.componentRef.setInput('usage', {
      ...EMPTY_CHAT_USAGE,
      totalTokens: 15000,
      estimatedCostUsd: null,
    });
    fixture.detectChanges();
    expect(panel.classList.contains('expanded')).toBe(true);
    expect(panel.querySelector('.cost')?.textContent).toContain('Unbekannt');
    expect(panel.querySelectorAll('dd')[3].textContent).toBe('15K');

    panel
      .querySelector('button')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }));
    fixture.detectChanges();
    expect(panel.inert).toBe(true);
    expect(line.inert).toBe(false);
    expect(root.querySelector('.mascot')?.classList.contains('faded')).toBe(false);
    expect(document.activeElement).toBe(textarea);
    expect(submitted).not.toHaveBeenCalled();
  });

  it('moves keyboard focus to the panel and returns it when Escape closes the panel', async () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('usage', EMPTY_CHAT_USAGE);
    fixture.detectChanges();
    const root = fixtureElement(fixture);
    const expand = root.querySelector<HTMLButtonElement>('.usage-toggle')!;
    expand.focus();
    expand.click();
    fixture.detectChanges();
    await fixture.whenStable();
    const collapse = root.querySelector<HTMLButtonElement>('.collapse-button')!;
    expect(document.activeElement).toBe(collapse);
    collapse.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    await fixture.whenStable();
    expect(document.activeElement).toBe(expand);
    expect(expand.getAttribute('aria-expanded')).toBe('false');
  });

  it('resets expansion when usage is removed and later supplied again', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('usage', EMPTY_CHAT_USAGE);
    fixture.detectChanges();
    const root = fixtureElement(fixture);
    root.querySelector<HTMLButtonElement>('.usage-toggle')!.click();
    fixture.detectChanges();
    fixture.componentRef.setInput('usage', null);
    fixture.detectChanges();
    expect(root.querySelector('ai-chat-usage-panel')).toBeNull();
    expect(root.querySelector('.mascot')?.classList.contains('faded')).toBe(false);
    fixture.componentRef.setInput('usage', EMPTY_CHAT_USAGE);
    fixture.detectChanges();
    expect(root.querySelector<HTMLElement>('.usage-panel')!.inert).toBe(true);
    expect(
      root.querySelector<HTMLButtonElement>('.usage-toggle')!.getAttribute('aria-expanded'),
    ).toBe('false');
  });

  it('keeps the mascot working through final text until the active turn finishes', () => {
    const fixture = createFixture([]);
    const mascot = fixtureElement(fixture).querySelector<HTMLImageElement>('.mascot')!;
    expect(mascot.getAttribute('src')).toBe('images/mascot-idle.png');
    expect(mascot.alt).toBe('');
    expect(mascot.getAttribute('aria-hidden')).toBe('true');

    const turn: ChatTurn = {
      runKey: 'active',
      status: 'active',
      content: [],
    };
    fixture.componentRef.setInput('turns', [turn]);
    fixture.detectChanges();
    expect(mascot.getAttribute('src')).toBe('images/maskot-working.png');

    fixture.componentRef.setInput('turns', [{ ...turn, content: DETAILS_CONTENT }]);
    fixture.componentRef.setInput('conversationStatus', null);
    fixture.detectChanges();
    expect(mascot.getAttribute('src')).toBe('images/maskot-working.png');

    for (const status of ['completed', 'failed', 'unknown'] as const) {
      fixture.componentRef.setInput('turns', [{ ...turn, status }]);
      fixture.detectChanges();
      expect(mascot.getAttribute('src')).toBe('images/mascot-idle.png');
    }
  });

  it('uses the consumer asset folder and ignores composer locks and conversation loading', () => {
    const fixture = createFixture([], { disabled: true });
    fixture.componentRef.setInput('mascotAssetPath', 'assets/chat-ui/images/');
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      placement: 'conversation',
      message: 'Starting',
    });
    fixture.detectChanges();
    const mascot = fixtureElement(fixture).querySelector<HTMLImageElement>('.mascot')!;
    expect(mascot.getAttribute('src')).toBe('assets/chat-ui/images/mascot-idle.png');

    fixture.componentRef.setInput('turns', [
      { runKey: 'active', status: 'active', content: [] },
      { runKey: 'completed', status: 'completed', content: [] },
    ]);
    fixture.detectChanges();
    expect(mascot.getAttribute('src')).toBe('assets/chat-ui/images/maskot-working.png');
  });

  it('shows enabled final-answer actions while active and retains them through automatic collapse', () => {
    const fixture = createFixture([]);
    const turn: ChatTurn = {
      runKey: 'first',
      status: 'active',
      content: DETAILS_CONTENT,
    };
    fixture.componentRef.setInput('turns', [turn]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const detail = element.querySelector<HTMLElement>('ai-chat-intermediate-message')!;
    const answerRow = element.querySelector('ai-chat-assistant-message')!.closest('.history-item');
    expect(isCollapsed(detail)).toBe(false);
    const actions = answerRow!.querySelector('.answer-actions');
    const activeToggle = answerRow!.querySelector<HTMLButtonElement>('.details-toggle')!;
    expect(activeToggle.disabled).toBe(false);
    expect(activeToggle.getAttribute('aria-expanded')).toBe('true');
    expect(element.querySelector('[data-scroll-anchor]')).toBe(answerRow);
    const anchor = answerRow!.getAttribute('data-scroll-anchor');
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([answerRow]);

    scrollTo.mockClear();
    fixture.componentRef.setInput('turns', [{ ...turn, status: 'completed' }]);
    fixture.detectChanges();
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([answerRow]);
    expect(answerRow!.getAttribute('data-scroll-anchor')).toBe(anchor);
    expect(scrollTo).not.toHaveBeenCalled();
    expect(isCollapsed(detail)).toBe(true);
    expect(
      detail.closest('ai-chat-history-item')?.querySelector<HTMLElement>('.collapse')?.inert,
    ).toBe(true);
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(true);
    const toggle = answerRow!.querySelector<HTMLButtonElement>('.details-toggle')!;
    expect(toggle).toBe(activeToggle);
    expect(answerRow!.querySelector('.answer-actions')).toBe(actions);
    expect(toggle.type).toBe('button');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.getAttribute('aria-label')).toBe('Details anzeigen');
    expect(toggle.querySelector('mat-icon')?.getAttribute('svgIcon')).toBe('ai-chat:list-tree');
    expect(
      toggle.closest('ai-chat-assistant-message')?.querySelector('.markdown')?.textContent,
    ).toBe('Answer');
    expect(toggle.closest('article')?.getAttribute('aria-label')).toBe('Antwort des Assistenten');
    toggle.click();
    fixture.detectChanges();
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([answerRow]);
    expect(answerRow!.getAttribute('data-scroll-anchor')).toBe(anchor);
    expect(isCollapsed(detail)).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.getAttribute('aria-label')).toBe('Details ausblenden');
  });

  it.each(['failed', 'unknown'] as const)(
    'keeps details visible for a %s turn even with explicit final text',
    (status) => {
      const fixture = createFixture([]);
      fixture.componentRef.setInput('turns', [
        { runKey: 'first', status, content: DETAILS_CONTENT },
      ]);
      fixture.detectChanges();
      const element = fixtureElement(fixture);
      expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-intermediate-message')!)).toBe(
        false,
      );
      expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(false);
      const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
      expect(toggle.disabled).toBe(false);
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      toggle.click();
      fixture.detectChanges();
      expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(true);
    },
  );

  it.each([
    { content: [] },
    {
      content: DETAILS_CONTENT.filter(
        (item) => item.kind !== 'tool' && item.kind !== 'intermediate',
      ),
    },
    { content: DETAILS_CONTENT.filter((item) => item.kind !== 'text' || !item.isFinal) },
  ])(
    'does not offer a details toggle without both details and an explicit final answer (%j)',
    ({ content }) => {
      const fixture = createFixture(content);
      expect(fixtureElement(fixture).querySelector('.details-toggle')).toBeNull();
      expect(fixtureElement(fixture).querySelector('[hidden]')).toBeNull();
    },
  );

  it('shows actions on every explicit final answer with shared expansion and the clicked answer anchor', () => {
    const fixture = createFixture([
      ...DETAILS_CONTENT,
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
    const toggles = element.querySelectorAll<HTMLButtonElement>('.details-toggle');
    expect(toggles).toHaveLength(2);
    expect(element.querySelectorAll('.answer-actions')).toHaveLength(2);
    expect(element.querySelector('.answer-actions')?.previousElementSibling?.textContent).toBe(
      'Answer',
    );
    const visibleText = timelineRows(element)
      .filter((item) => !isCollapsed(item))
      .map((item) => item.querySelector('.markdown')?.textContent ?? item.textContent);
    expect(visibleText).toEqual([
      'Request',
      'Answer',
      'Another final',
      'Later ordinary text',
      'Retained failure',
    ]);
    toggles[1].click();
    fixture.detectChanges();
    expect([...toggles].map((toggle) => toggle.getAttribute('aria-expanded'))).toEqual([
      'true',
      'true',
    ]);
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([
      toggles[1].closest('.history-item'),
    ]);
  });

  it('preserves manual toggling while active across snapshots and automatically collapses on completion', () => {
    const fixture = createFixture([]);
    const turn: ChatTurn = { runKey: 'active', status: 'active', content: DETAILS_CONTENT };
    fixture.componentRef.setInput('turns', [turn]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    toggle.click();
    fixture.detectChanges();
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(true);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');

    const content: readonly ChatContent[] = [
      ...DETAILS_CONTENT,
      { kind: 'intermediate', id: 'new-detail', text: 'More checking' },
    ];
    fixture.componentRef.setInput('turns', [{ ...turn, content }]);
    fixture.detectChanges();
    expect(element.querySelector('.details-toggle')).toBe(toggle);
    for (const detail of element.querySelectorAll<HTMLElement>('ai-chat-intermediate-message')) {
      expect(isCollapsed(detail)).toBe(true);
    }
    toggle.click();
    fixture.detectChanges();
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(false);

    fixture.componentRef.setInput('turns', [{ ...turn, status: 'completed', content }]);
    fixture.detectChanges();
    expect(element.querySelector('.details-toggle')).toBe(toggle);
    expect(toggle.disabled).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(true);
  });

  it('renders the final action bar before details arrive and retains the bar when controls become available', () => {
    const fixture = createFixture([]);
    const answer = DETAILS_CONTENT[3];
    fixture.componentRef.setInput('turns', [
      { runKey: 'active', status: 'active', content: [answer] },
    ]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const actions = element.querySelector('.answer-actions');
    expect(actions).not.toBeNull();
    expect(actions!.querySelector('button')).toBeNull();

    fixture.componentRef.setInput('turns', [
      { runKey: 'active', status: 'active', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    expect(element.querySelector('.answer-actions')).toBe(actions);
    expect(actions!.querySelector<HTMLButtonElement>('.details-toggle')!.disabled).toBe(false);
  });

  it('remembers manual detail expansion per historical run across new inputs and resets on recreation', () => {
    const fixture = createFixture(DETAILS_CONTENT);
    const element = fixtureElement(fixture);
    element.querySelector<HTMLButtonElement>('.details-toggle')!.click();
    fixture.detectChanges();
    const historical = fixture.componentInstance.turns()[0];
    const next: ChatTurn = { ...historical, runKey: 'next', content: [...DETAILS_CONTENT] };
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
      { runKey: 'pending', status: 'active', content: [] },
    ]);
    fixture.detectChanges();
    expect(toggles[0].getAttribute('aria-expanded')).toBe('false');
    toggles[1].click();
    fixture.detectChanges();
    expect(toggles[1].getAttribute('aria-expanded')).toBe('true');
    fixture.destroy();
    const recreated = createFixture(DETAILS_CONTENT);
    expect(
      fixtureElement(recreated).querySelector('.details-toggle')?.getAttribute('aria-expanded'),
    ).toBe('false');
  });

  it('keeps unphased session text visible without final-answer controls or automatic collapse', () => {
    const time = '2026-10-21T12:00:00Z';
    const turn: PresentedTurn = {
      part_kind: 'turn',
      usage: EMPTY_USAGE,
      lifecycle: { run_id: 'run', status: 'running', started_at: time, finished_at: null },
      parts: [
        { part_kind: 'text', phase: 'commentary', content: 'Checking' },
        { part_kind: 'tool-call', tool_call_id: 'call', tool_name: 'check', status: 'success' },
        { part_kind: 'text', phase: null, content: 'Unphased answer' },
      ],
    };
    const fixture = createFixture([]);
    const element = fixtureElement(fixture);

    for (const status of ['running', 'completed'] as const) {
      fixture.componentRef.setInput(
        'turns',
        presentSession({
          session_id: 'session',
          expires_at: time,
          error: null,
          usage: EMPTY_USAGE,
          history: [
            {
              ...turn,
              lifecycle: {
                ...turn.lifecycle,
                status,
                finished_at: status === 'completed' ? time : null,
              },
            },
          ],
        }),
      );
      fixture.detectChanges();
      expect(element.querySelector('ai-chat-assistant-message .markdown')?.textContent).toBe(
        'Unphased answer',
      );
      expect(element.querySelector('.details-toggle')).toBeNull();
      expect(element.querySelector('[data-scroll-anchor]')).toBeNull();
      expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-intermediate-message')!)).toBe(
        false,
      );
      expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(false);
    }
  });

  it('retains native artifacts and shared run detail expansion through replacement snapshots and nullable ID capture', () => {
    const lifecycle: PresentedTurn['lifecycle'] = {
      run_id: null,
      status: 'running',
      started_at: '2026-10-21T12:00:00Z',
      finished_at: null,
    };
    const first: PresentedTurn = {
      part_kind: 'turn',
      usage: EMPTY_USAGE,
      lifecycle,
      parts: [
        { part_kind: 'tool-call', tool_call_id: 'call', tool_name: 'publish', status: 'running' },
        {
          part_kind: 'artifact',
          artifact: {
            artifact_id: 'card',
            type: 'json',
            run_id: 'run',
            created_at: lifecycle.started_at,
            content: { title: 'Result', payload: { value: 'Long result' } },
          },
        },
      ],
    };
    const snapshot: PresentedSession = {
      error: null,
      usage: EMPTY_USAGE,
      session_id: 's',
      expires_at: lifecycle.started_at,
      history: [first],
    };
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', presentSession(snapshot));
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const card = element.querySelector('ai-chat-artifact-card')!;
    const body = card.querySelector<HTMLElement>('.artifact-body')!;
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 500 });
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 100 });
    const artifactComponent = fixture.debugElement
      .query(By.directive(ArtifactCardComponent))
      .injector.get(ArtifactCardComponent);
    artifactComponent['measure']();
    fixture.detectChanges();
    card.querySelector<HTMLButtonElement>('.artifact-toggle')!.click();
    fixture.detectChanges();
    const completed = { ...lifecycle, run_id: 'run', status: 'completed' as const };
    const updated: PresentedSession = {
      ...snapshot,
      history: [
        {
          ...first,
          lifecycle: completed,
          parts: [
            {
              part_kind: 'tool-call',
              tool_call_id: 'call',
              tool_name: 'publish',
              status: 'success',
            },
            first.parts[1],
          ],
        },
        { part_kind: 'user-prompt', content: ['same', 'same'] },
        {
          part_kind: 'turn',
          usage: EMPTY_USAGE,
          lifecycle: completed,
          parts: [{ part_kind: 'text', phase: 'final_answer', content: 'Answer' }],
        },
      ],
    };
    fixture.componentRef.setInput('turns', presentSession(updated));
    fixture.detectChanges();
    expect(element.querySelector('ai-chat-artifact-card')).toBe(card);
    expect(card.querySelector('.artifact-body')).toBe(body);
    expect(card.querySelector('.artifact-toggle')?.getAttribute('aria-expanded')).toBe('true');
    expect(element.querySelector('ai-chat-tool-call')?.textContent).toContain('publish');
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(true);
    element.querySelector<HTMLButtonElement>('.details-toggle')!.click();
    fixture.detectChanges();
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-tool-call')!)).toBe(false);
    fixture.componentRef.setInput('turns', presentSession(structuredClone(updated)));
    fixture.detectChanges();
    expect(element.querySelector('.details-toggle')?.getAttribute('aria-expanded')).toBe('true');
    expect(card.querySelector('.artifact-toggle')?.getAttribute('aria-expanded')).toBe('true');
    expect(element.querySelectorAll('ai-chat-user-message')).toHaveLength(2);
    expect(element.querySelector('ai-chat-artifact-card')).toBe(card);
    fixture.componentRef.setInput(
      'turns',
      presentSession({ ...updated, session_id: 'another-session' }),
    );
    fixture.detectChanges();
    expect(element.querySelector('.details-toggle')?.getAttribute('aria-expanded')).toBe('false');
    expect(element.querySelector('ai-chat-artifact-card')).not.toBe(card);
  });

  it('preserves interleaved artifact nodes, renderer DOM state and order across toggles', () => {
    const templateFixture = TestBed.createComponent(RendererTemplateHost);
    templateFixture.detectChanges();
    const fixture = createFixture([
      DETAILS_CONTENT[0],
      DETAILS_CONTENT[1],
      {
        kind: 'artifact',
        id: 'card',
        type: 'known',
        headline: 'Card',
        payload: { label: 'retained' },
      },
      DETAILS_CONTENT[2],
      DETAILS_CONTENT[3],
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
    const rows = timelineRows(element);
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    for (let index = 0; index < 2; index++) {
      toggle.click();
      fixture.detectChanges();
      expect(element.querySelector('ai-chat-artifact-card')).toBe(card);
      expect(card.querySelector('.artifact-body')).toBe(rendererBody);
      expect(card.querySelector('input')?.value).toBe('renderer local state');
      expect(timelineRows(element)).toEqual(rows);
    }
  });

  it('selects the clicked answer history item for native anchoring without manually scrolling', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', [
      { runKey: 'first', status: 'completed', content: DETAILS_CONTENT },
      { runKey: 'second', status: 'completed', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const history = element.querySelector<HTMLElement>('.history')!;
    const toggles = element.querySelectorAll<HTMLButtonElement>('.details-toggle');
    const measurements = [...toggles].map((toggle) => vi.spyOn(toggle, 'getBoundingClientRect'));
    history.scrollTop = 300;
    scrollTo.mockClear();
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([
      toggles[1].closest('.history-item'),
    ]);

    for (const index of [0, 1, 1, 0]) {
      toggles[index].click();
      fixture.detectChanges();
      expect([...element.querySelectorAll('.history-scroll-anchor')]).toEqual([
        toggles[index].closest('.history-item'),
      ]);
      expect(history.scrollTop).toBe(300);
      expect(scrollTo).not.toHaveBeenCalled();
    }
    expect([...toggles].map((toggle) => toggle.getAttribute('aria-expanded'))).toEqual([
      'false',
      'false',
    ]);
    for (const measurement of measurements) expect(measurement).not.toHaveBeenCalled();
  });

  it.each([null, 'turn-1'])(
    'anchors the artifact wrapper for expansion and collapse with run key %s',
    (runKey) => {
      const fixture = createFocusFixture(runKey);
      const element = fixtureElement(fixture);
      const history = element.querySelector<HTMLElement>('.history')!;
      const toggle = element.querySelector<HTMLButtonElement>('.artifact-toggle')!;
      const wrapper = toggle.closest('.history-item')!;
      const body = element.querySelector('.artifact-body')!;
      const measurement = vi.spyOn(wrapper, 'getBoundingClientRect');
      history.scrollTop = 300;
      scrollTo.mockClear();

      for (const expanded of [true, false]) {
        toggle.click();
        fixture.detectChanges();
        expect([...element.querySelectorAll('.history-scroll-anchor')]).toEqual([wrapper]);
        expect(wrapper.getAttribute('data-scroll-anchor')).toBe(
          JSON.stringify([runKey, 'focus-artifact']),
        );
        expect(toggle.classList.contains('history-scroll-anchor')).toBe(false);
        expect(body.classList.contains('artifact-body--expanded')).toBe(expanded);
        expect(toggle.getAttribute('aria-expanded')).toBe(String(expanded));
        expect(history.scrollTop).toBe(300);
        expect(scrollTo).not.toHaveBeenCalled();
      }
      expect(measurement).not.toHaveBeenCalled();

      if (runKey !== null) {
        const detailsToggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
        detailsToggle.click();
        fixture.detectChanges();
        expect([...element.querySelectorAll('.history-scroll-anchor')]).toEqual([
          detailsToggle.closest('.history-item'),
        ]);
        toggle.click();
        fixture.detectChanges();
        expect([...element.querySelectorAll('.history-scroll-anchor')]).toEqual([wrapper]);
      }

      element.querySelector('textarea')!.dispatchEvent(new FocusEvent('focus'));
      fixture.detectChanges();
      expect(element.querySelector('.history-scroll-anchor')).toBeNull();
      expect(scrollTo).toHaveBeenCalledOnce();
    },
  );

  it('clears native detail anchoring for incoming content and composer scrolling', () => {
    const fixture = createFixture(DETAILS_CONTENT);
    const element = fixtureElement(fixture);
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    const answerRow = toggle.closest('.history-item')!;
    toggle.click();
    fixture.detectChanges();
    expect(answerRow.classList.contains('history-scroll-anchor')).toBe(true);

    fixture.componentRef.setInput('turns', [
      { runKey: 'turn-1', status: 'completed', content: [...DETAILS_CONTENT] },
    ]);
    fixture.detectChanges();
    expect(element.querySelector('.history-scroll-anchor')).toBeNull();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');

    toggle.click();
    fixture.detectChanges();
    expect(answerRow.classList.contains('history-scroll-anchor')).toBe(true);
    element.querySelector('textarea')!.dispatchEvent(new FocusEvent('focus'));
    fixture.detectChanges();
    expect(element.querySelector('.history-scroll-anchor')).toBeNull();
  });

  it('retains bottom scrolling when completion has no existing answer anchor', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', [
      { runKey: 'first', status: 'active', content: DETAILS_CONTENT.slice(0, -1) },
    ]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    expect(element.querySelector('.history-scroll-anchor')).toBeNull();
    expect(element.querySelector('ai-chat-assistant-message')).toBeNull();
    scrollTo.mockClear();

    fixture.componentRef.setInput('turns', [
      { runKey: 'first', status: 'completed', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    expect(element.querySelector('[data-scroll-anchor]')).toBe(
      element.querySelector('ai-chat-assistant-message')!.closest('.history-item'),
    );
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([
      element.querySelector('[data-scroll-anchor]'),
    ]);
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-intermediate-message')!)).toBe(
      true,
    );
    expect(scrollTo).toHaveBeenCalledOnce();
  });

  it('uses the same shared run answer anchor before and after every section completes', () => {
    const fixture = createFixture([]);
    const first: ChatTurn = { runKey: 'shared', status: 'completed', content: DETAILS_CONTENT };
    const second: ChatTurn = {
      runKey: 'shared',
      status: 'active',
      content: [{ kind: 'intermediate', id: 'later-detail', text: 'Still checking' }],
    };
    fixture.componentRef.setInput('turns', [first, second]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const answerRow = element.querySelector('ai-chat-assistant-message')!.closest('.history-item');
    expect(element.querySelector('[data-scroll-anchor]')).toBe(answerRow);
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([answerRow]);
    const toggle = element.querySelector<HTMLButtonElement>('.details-toggle')!;
    expect(toggle.disabled).toBe(false);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    scrollTo.mockClear();

    fixture.componentRef.setInput('turns', [first, { ...second, status: 'completed' }]);
    fixture.detectChanges();
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([answerRow]);
    expect(element.querySelector('.details-toggle')).toBe(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('reveals a replacement final answer instead of selecting the previous answer anchor', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', [
      { runKey: 'first', status: 'active', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    const element = fixtureElement(fixture);
    const previous = element.querySelector('[data-scroll-anchor]');
    scrollTo.mockClear();

    fixture.componentRef.setInput('turns', [
      {
        runKey: 'first',
        status: 'completed',
        content: DETAILS_CONTENT.map((item) =>
          item.id === 'answer' ? { ...item, id: 'replacement-answer' } : item,
        ),
      },
    ]);
    fixture.detectChanges();
    expect(element.querySelector('[data-scroll-anchor]')).not.toBe(previous);
    expect([...element.getElementsByClassName('history-scroll-anchor')]).toEqual([
      element.querySelector('[data-scroll-anchor]'),
    ]);
    expect(scrollTo).toHaveBeenCalledOnce();
  });

  it('retains bottom scrolling when remembered expansion prevents automatic collapse', () => {
    const fixture = createFixture(DETAILS_CONTENT);
    const element = fixtureElement(fixture);
    element.querySelector<HTMLButtonElement>('.details-toggle')!.click();
    fixture.detectChanges();
    fixture.componentRef.setInput('turns', [
      { runKey: 'turn-1', status: 'active', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    scrollTo.mockClear();

    fixture.componentRef.setInput('turns', [
      { runKey: 'turn-1', status: 'completed', content: DETAILS_CONTENT },
    ]);
    fixture.detectChanges();
    expect(isCollapsed(element.querySelector<HTMLElement>('ai-chat-intermediate-message')!)).toBe(
      false,
    );
    expect(element.querySelector('.history-scroll-anchor')).toBeNull();
    expect(scrollTo).toHaveBeenCalledOnce();
  });

  it.each(['completed', 'failed', 'unknown'] as const)(
    'retains bottom scrolling when a %s update does not collapse any details',
    (status) => {
      const fixture = createFixture([]);
      const content = status === 'completed' ? INITIAL_MESSAGES : DETAILS_CONTENT;
      fixture.componentRef.setInput('turns', [{ runKey: 'first', status: 'active', content }]);
      fixture.detectChanges();
      scrollTo.mockClear();

      fixture.componentRef.setInput('turns', [{ runKey: 'first', status, content }]);
      fixture.detectChanges();
      expect(fixtureElement(fixture).querySelector('.history-scroll-anchor')).toBeNull();
      expect(scrollTo).toHaveBeenCalledOnce();
    },
  );

  it('renders ordered host messages and applies Markdown only to assistant text', () => {
    const fixture = createFixture(INITIAL_MESSAGES);
    const messageElements = fixtureElement(fixture).querySelectorAll<HTMLElement>(
      'ai-chat-user-message, ai-chat-assistant-message, ai-chat-intermediate-message',
    );

    expect(messageElements).toHaveLength(2);
    expect(messageElements[0].matches('ai-chat-user-message')).toBe(true);
    expect(messageElements[0].querySelector('article')).not.toBeNull();
    expect(messageElements[0].querySelector('article')?.getAttribute('aria-label')).toBe(
      'Nachricht des Benutzers',
    );
    expect(messageElements[0].textContent).toContain('**literal user text**');
    expect(messageElements[0].querySelector('strong')).toBeNull();
    expect(messageElements[0].querySelector('img')).toBeNull();
    expect(messageElements[0].textContent).toContain('<img src=x>\nNext line');
    expect(messageElements[1].matches('ai-chat-assistant-message')).toBe(true);
    expect(messageElements[1].querySelector('article')).not.toBeNull();
    expect(messageElements[1].querySelector('strong')?.textContent).toBe(
      'formatted assistant text',
    );
  });

  it('renders turn-owned content in order and preserves historical failures with a current error', () => {
    const fixture = createFixture([]);
    fixture.componentRef.setInput('turns', [
      {
        runKey: 'first',
        status: 'failed',
        content: [
          { kind: 'text', isFinal: false, id: 'first-user', role: 'user', text: 'First' },
          { kind: 'failure', id: 'first-failure', text: 'Historical failure' },
        ],
      },
      {
        runKey: 'second',
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
    const rows = timelineRows(element);
    expect(rows.map((row) => row.tagName)).toEqual([
      'AI-CHAT-USER-MESSAGE',
      'AI-CHAT-STATUS',
      'AI-CHAT-USER-MESSAGE',
      'AI-CHAT-INTERMEDIATE-MESSAGE',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-ARTIFACT-CARD',
      'AI-CHAT-STATUS',
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
    const rows = timelineRows(element);
    expect(rows[0].matches('ai-chat-intermediate-message')).toBe(true);
    expect(rows[0].querySelector('article')).not.toBeNull();
    expect(rows[0].querySelector('article')?.getAttribute('aria-label')).toBe(
      'Zwischenmeldung des Assistenten',
    );
    expect(rows[0].querySelector('strong')?.textContent).toBe('Checking');
    expect(rows[0].querySelector('script')).toBeNull();
    expect(rows[1].matches('ai-chat-tool-call')).toBe(true);
    expect(rows[2].matches('ai-chat-assistant-message')).toBe(true);
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
    expect(timelineRows(element).map((child) => child.tagName)).toEqual([
      'AI-CHAT-USER-MESSAGE',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-ARTIFACT-CARD',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-TOOL-CALL',
      'AI-CHAT-STATUS',
    ]);
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
    expect(element.querySelectorAll('ai-chat-status.error')).toHaveLength(1);
    setContent(fixture, [
      ...fixture.componentInstance.turns()[0].content,
      { kind: 'text', isFinal: false, id: 'next-user', role: 'user', text: 'Continue' },
    ]);
    fixture.componentRef.setInput('conversationStatus', null);
    fixture.detectChanges();
    expect(element.querySelectorAll('ai-chat-status.error')).toHaveLength(1);
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

    textarea.focus();
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
    expect(
      fixtureElement(fixture).querySelectorAll(
        'ai-chat-user-message, ai-chat-assistant-message, ai-chat-intermediate-message',
      ),
    ).toHaveLength(0);
    expect(document.activeElement).toBe(textarea);
  });

  it.each(['mouse', 'touch', 'pen', 'mousedown'])(
    'preserves composer focus when sending with %s',
    (pointerType) => {
      const fixture = createFixture([]);
      const element = fixtureElement(fixture);
      const textarea = element.querySelector('textarea') as HTMLTextAreaElement;
      const button = element.querySelector('.send-button') as HTMLButtonElement;
      const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
      textarea.value = 'Hello';
      textarea.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      textarea.focus();
      const blur = vi.fn();
      textarea.addEventListener('blur', blur);
      const press =
        pointerType === 'mousedown'
          ? new MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true })
          : new PointerEvent('pointerdown', {
              pointerType,
              button: 0,
              isPrimary: true,
              bubbles: true,
              cancelable: true,
            });

      button.dispatchEvent(press);
      expect(press.defaultPrevented).toBe(true);
      expect(emit).not.toHaveBeenCalled();
      button.click();
      expect(emit).toHaveBeenCalledOnce();
      fixture.componentRef.setInput('composerEditingDisabled', true);
      fixture.detectChanges();
      emit.mock.calls[0][0].acknowledge();
      fixture.detectChanges();
      expect(textarea.value).toBe('');
      expect(document.activeElement).toBe(textarea);
      expect(blur).not.toHaveBeenCalled();
    },
  );

  it.each(
    ['.details-toggle', '.artifact-toggle'].flatMap((selector) =>
      ['mouse', 'touch', 'pen', 'mousedown'].map((pointerType) => ({ selector, pointerType })),
    ),
  )(
    'preserves composer focus when toggling $selector with $pointerType',
    ({ selector, pointerType }) => {
      const fixture = createFocusFixture();
      const element = fixtureElement(fixture);
      const textarea = element.querySelector('textarea')!;
      const button = element.querySelector<HTMLButtonElement>(selector)!;
      textarea.focus();
      const blur = vi.fn();
      textarea.addEventListener('blur', blur);

      for (const expanded of [true, false]) {
        const press =
          pointerType === 'mousedown'
            ? new MouseEvent('mousedown', { button: 0, bubbles: true, cancelable: true })
            : new PointerEvent('pointerdown', {
                pointerType,
                button: 0,
                isPrimary: true,
                bubbles: true,
                cancelable: true,
              });
        button.dispatchEvent(press);
        expect(press.defaultPrevented).toBe(true);
        button.click();
        fixture.detectChanges();
        expect(button.getAttribute('aria-expanded')).toBe(String(expanded));
        expect(document.activeElement).toBe(textarea);
        expect(blur).not.toHaveBeenCalled();
      }
    },
  );

  it.each(
    FOCUS_CONTROLS.flatMap((selector) =>
      ['pointerdown', 'mousedown'].map((eventType) => ({ selector, eventType })),
    ),
  )(
    'prevents $eventType focus on $selector regardless of the focused element or mouse button',
    ({ selector, eventType }) => {
      const fixture = createFocusFixture();
      const element = fixtureElement(fixture);
      const textarea = element.querySelector('textarea')!;
      const button = element.querySelector<HTMLButtonElement>(selector)!;
      button.focus();
      const press = new MouseEvent(eventType, { button: 0, bubbles: true, cancelable: true });
      button.dispatchEvent(press);
      expect(press.defaultPrevented).toBe(true);
      expect(document.activeElement).toBe(button);

      textarea.focus();
      const secondaryPress = new MouseEvent(eventType, {
        button: 2,
        bubbles: true,
        cancelable: true,
      });
      button.dispatchEvent(secondaryPress);
      expect(secondaryPress.defaultPrevented).toBe(true);
    },
  );

  it.each(FOCUS_CONTROLS)('retains keyboard focus on %s when activated', (selector) => {
    const fixture = createFocusFixture();
    const button = fixtureElement(fixture).querySelector<HTMLButtonElement>(selector)!;
    button.focus();
    const key = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    button.dispatchEvent(key);
    expect(key.defaultPrevented).toBe(false);
    button.click();
    fixture.detectChanges();
    expect(document.activeElement).toBe(button);
  });

  it.each(['insertText', 'insertFromPaste', 'deleteContentBackward', 'insertCompositionText'])(
    'blocks %s while sending without disabling or blurring the textarea',
    (inputType) => {
      const fixture = createFixture([]);
      const element = fixtureElement(fixture);
      const textarea = element.querySelector('textarea') as HTMLTextAreaElement;
      const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
      textarea.value = 'Retained draft';
      textarea.dispatchEvent(new Event('input'));
      textarea.focus();
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      expect(emit).toHaveBeenCalledOnce();
      fixture.componentRef.setInput('composerDisabled', true);
      fixture.componentRef.setInput('composerEditingDisabled', true);
      fixture.detectChanges();

      const beforeInput = new InputEvent('beforeinput', {
        inputType,
        data: 'x',
        bubbles: true,
        cancelable: true,
      });
      textarea.dispatchEvent(beforeInput);
      expect(beforeInput.defaultPrevented).toBe(true);
      expect(textarea.disabled).toBe(false);
      expect(textarea.readOnly).toBe(false);
      expect(textarea.getAttribute('aria-disabled')).toBe('true');
      expect(document.activeElement).toBe(textarea);
      expect((element.querySelector('.send-button') as HTMLButtonElement).disabled).toBe(true);
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
      expect(emit).toHaveBeenCalledOnce();

      fixture.componentRef.setInput('composerDisabled', false);
      fixture.componentRef.setInput('composerEditingDisabled', false);
      fixture.detectChanges();
      const allowedInput = new InputEvent('beforeinput', {
        inputType: 'insertText',
        cancelable: true,
      });
      textarea.dispatchEvent(allowedInput);
      expect(allowedInput.defaultPrevented).toBe(false);
      expect(textarea.hasAttribute('aria-disabled')).toBe(false);
      textarea.value = 'Editable again';
      textarea.dispatchEvent(new Event('input'));
      textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      expect(emit).toHaveBeenLastCalledWith(expect.objectContaining({ text: 'Editable again' }));
    },
  );

  it('restores the draft after non-cancellable edits and keeps acknowledgement clearing intact', () => {
    const fixture = createFixture([]);
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
    const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
    textarea.value = 'Original draft';
    textarea.dispatchEvent(new Event('input'));
    textarea.focus();
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.componentRef.setInput('composerEditingDisabled', true);
    fixture.detectChanges();
    const beforeInput = new InputEvent('beforeinput', {
      inputType: 'insertCompositionText',
      cancelable: false,
    });
    textarea.dispatchEvent(beforeInput);
    textarea.value = 'Unexpected composition edit';
    textarea.dispatchEvent(
      new InputEvent('input', { inputType: 'insertCompositionText', isComposing: true }),
    );
    fixture.detectChanges();
    expect(textarea.value).toBe('Original draft');
    expect(document.activeElement).toBe(textarea);

    emit.mock.calls[0][0].acknowledge();
    fixture.detectChanges();
    expect(textarea.value).toBe('');
    textarea.value = 'Autocorrect without beforeinput';
    textarea.dispatchEvent(new Event('input'));
    expect(textarea.value).toBe('');
    expect(document.activeElement).toBe(textarea);
  });

  it('allows drafting during an assistant response while keeping submission blocked', () => {
    const fixture = createFixture([]);
    const element = fixtureElement(fixture);
    const textarea = element.querySelector('textarea') as HTMLTextAreaElement;
    const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
    fixture.componentRef.setInput('composerDisabled', true);
    fixture.componentRef.setInput('composerEditingDisabled', false);
    fixture.detectChanges();
    const edit = new InputEvent('beforeinput', { cancelable: true, inputType: 'insertText' });
    textarea.dispatchEvent(edit);
    expect(edit.defaultPrevented).toBe(false);
    textarea.value = 'Next question';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(textarea.value).toBe('Next question');
    expect((element.querySelector('.send-button') as HTMLButtonElement).disabled).toBe(true);
    textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(emit).not.toHaveBeenCalled();
    fixture.componentRef.setInput('composerDisabled', false);
    fixture.detectChanges();
    expect(textarea.value).toBe('Next question');
    (element.querySelector('.send-button') as HTMLButtonElement).click();
    expect(emit).toHaveBeenCalledWith(expect.objectContaining({ text: 'Next question' }));
  });

  it('does not focus the composer on initialization or readiness and lock changes', () => {
    const fixture = createFixture([], { disabled: true });
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
    expect(document.activeElement).not.toBe(textarea);
    const focus = vi.spyOn(textarea, 'focus');
    fixture.componentRef.setInput('composerDisabled', false);
    fixture.detectChanges();
    expect(document.activeElement).not.toBe(textarea);
    textarea.focus();
    focus.mockClear();
    fixture.componentRef.setInput('composerEditingDisabled', true);
    fixture.detectChanges();
    expect(document.activeElement).toBe(textarea);
    textarea.blur();
    fixture.componentRef.setInput('composerEditingDisabled', false);
    fixture.detectChanges();
    expect(document.activeElement).not.toBe(textarea);
    expect(focus).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'does not reclaim focus on acknowledgement after the user moves away (%s)',
    (blur) => {
      const fixture = createFixture([]);
      const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
      const emit = vi.spyOn(fixture.componentInstance.messageSubmitted, 'emit');
      const other = document.createElement('button');
      document.body.append(other);
      try {
        textarea.focus();
        textarea.value = 'Hello';
        textarea.dispatchEvent(new Event('input'));
        textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        fixture.componentRef.setInput('composerDisabled', true);
        fixture.componentRef.setInput('composerEditingDisabled', true);
        fixture.detectChanges();
        other.focus();
        if (blur) other.blur();
        emit.mock.calls[0][0].acknowledge();
        fixture.componentRef.setInput('composerEditingDisabled', false);
        fixture.detectChanges();
        expect(textarea.value).toBe('');
        expect(document.activeElement).toBe(blur ? document.body : other);
        fixture.componentRef.setInput('composerDisabled', false);
        fixture.detectChanges();
        expect(document.activeElement).toBe(blur ? document.body : other);
      } finally {
        other.remove();
      }
    },
  );

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
    expect(
      fixtureElement(fixture).querySelectorAll(
        'ai-chat-user-message, ai-chat-assistant-message, ai-chat-intermediate-message',
      ),
    ).toHaveLength(0);

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

    const messages = fixtureElement(fixture).querySelectorAll<HTMLElement>(
      'ai-chat-user-message, ai-chat-assistant-message, ai-chat-intermediate-message',
    );
    expect(messages).toHaveLength(1);
    expect(messages[0].textContent).toContain('Replacement state');
  });

  it('scrolls history to the bottom each time the textarea gains focus', () => {
    const fixture = createFixture(INITIAL_MESSAGES);
    const element = fixtureElement(fixture);
    const textarea = element.querySelector('textarea') as HTMLTextAreaElement;
    const history = element.querySelector('.history') as HTMLElement;
    Object.defineProperty(history, 'scrollHeight', { configurable: true, value: 1000 });
    scrollTo.mockClear();

    for (let attempt = 0; attempt < 2; attempt++) {
      history.scrollTop = 100;
      textarea.focus();
      fixture.detectChanges();
      expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ top: 1000, behavior: 'smooth' });
      scrollTo.mockClear();
      textarea.blur();
      fixture.detectChanges();
      expect(scrollTo).not.toHaveBeenCalled();
    }
  });

  it('scrolls after delayed viewport resizes only while the textarea is focused', async () => {
    const viewport = new EventTarget();
    vi.stubGlobal('visualViewport', viewport);
    const fixture = createFixture(INITIAL_MESSAGES);
    const element = fixtureElement(fixture);
    const textarea = element.querySelector('textarea') as HTMLTextAreaElement;
    const button = element.querySelector('.send-button') as HTMLButtonElement;
    const history = element.querySelector('.history') as HTMLElement;
    scrollTo.mockClear();
    viewport.dispatchEvent(new Event('resize'));
    await fixture.whenStable();
    expect(scrollTo).not.toHaveBeenCalled();

    textarea.focus();
    await fixture.whenStable();
    scrollTo.mockClear();
    for (const height of [1000, 1200]) {
      Object.defineProperty(history, 'scrollHeight', { configurable: true, value: height });
      viewport.dispatchEvent(new Event('resize'));
      await fixture.whenStable();
      expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ top: height, behavior: 'smooth' });
      scrollTo.mockClear();
    }

    textarea.value = 'Hello';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    button.focus();
    viewport.dispatchEvent(new Event('resize'));
    await fixture.whenStable();
    expect(scrollTo).not.toHaveBeenCalled();

    textarea.focus();
    await fixture.whenStable();
    scrollTo.mockClear();
    viewport.dispatchEvent(new Event('resize'));
    await fixture.whenStable();
    expect(scrollTo).toHaveBeenCalledOnce();
  });

  it('removes the viewport resize listener on blur and destruction', () => {
    const viewport = new EventTarget();
    const add = vi.spyOn(viewport, 'addEventListener');
    const remove = vi.spyOn(viewport, 'removeEventListener');
    vi.stubGlobal('visualViewport', viewport);
    const fixture = createFixture([]);
    const textarea = fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement;
    textarea.focus();
    const firstListener = add.mock.calls[0][1];
    textarea.blur();
    expect(remove).toHaveBeenCalledExactlyOnceWith('resize', firstListener);
    textarea.focus();
    const secondListener = add.mock.calls[1][1];
    fixture.destroy();
    expect(remove).toHaveBeenLastCalledWith('resize', secondListener);
    expect(remove).toHaveBeenCalledTimes(2);
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
    expect(fixtureElement(fixture).querySelector('ai-chat-status.delayed')).not.toBeNull();
    expect(fixtureElement(fixture).querySelector('.content')).toBeNull();
    expect(
      (fixtureElement(fixture).querySelector('textarea') as HTMLTextAreaElement).disabled,
    ).toBe(false);
    vi.advanceTimersByTime(299);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.content')).toBeNull();
    vi.advanceTimersByTime(1);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Sending',
    );
    expect(fixtureElement(fixture).querySelector('ai-chat-status p')).toBeNull();
    const sendingLabel = fixtureElement(fixture).querySelector('.content');
    fixture.componentRef.setInput('conversationStatus', {
      kind: 'loading',
      message: 'Generating',
      placement: 'assistant',
    });
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.loading-dots')?.getAttribute('aria-label')).toBe(
      'Generating',
    );
    const generatingLabel = fixtureElement(fixture).querySelector('.content');
    expect(generatingLabel!.classList.contains('fade')).toBe(false);
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
    expect(fixtureElement(fixture).querySelector('ai-chat-status')?.textContent).toContain(
      'Failed',
    );
    fixture.componentRef.setInput('conversationStatus', sending);
    fixture.detectChanges();
    expect(fixtureElement(fixture).querySelector('.content')).toBeNull();
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
    expect(fixtureElement(fixture).querySelector('ai-chat-status p')?.textContent).toBe(
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
    ).toBe(false);
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
    (fixtureElement(fixture).querySelector('.action') as HTMLButtonElement).click();

    expect(actionEmit).toHaveBeenCalledWith('retry-turn');
    expect(fixtureElement(fixture).querySelector('.content')!.classList.contains('fade')).toBe(
      false,
    );
  });
});

function createFixture(
  messages: readonly ChatContent[],
  options: { disabled?: boolean } = {},
): ComponentFixture<ChatUiComponent> {
  const fixture = TestBed.createComponent(ChatUiComponent);
  fixture.componentRef.setInput('bannerTitle', 'Welcome');
  fixture.componentRef.setInput('bannerDescription', 'Description');
  setContent(fixture, messages);
  fixture.componentRef.setInput('composerDisabled', options.disabled ?? false);
  fixture.detectChanges();
  return fixture;
}

function createFocusFixture(runKey: string | null = 'turn-1'): ComponentFixture<ChatUiComponent> {
  const fixture = createFixture([
    ...DETAILS_CONTENT,
    {
      kind: 'artifact',
      id: 'focus-artifact',
      type: 'json',
      headline: 'Result',
      payload: { value: 'Long result' },
    },
  ]);
  fixture.componentRef.setInput(
    'turns',
    fixture.componentInstance.turns().map((turn) => ({ ...turn, runKey })),
  );
  fixture.detectChanges();
  const element = fixtureElement(fixture);
  const body = element.querySelector<HTMLElement>('.artifact-body')!;
  Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 500 });
  Object.defineProperty(body, 'clientHeight', { configurable: true, value: 100 });
  const artifact = fixture.debugElement
    .query(By.directive(ArtifactCardComponent))
    .injector.get(ArtifactCardComponent);
  artifact['measure']();
  const textarea = element.querySelector('textarea')!;
  textarea.value = 'Hello';
  textarea.dispatchEvent(new Event('input'));
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
    content.length === 0 ? [] : [{ runKey: 'turn-1', status: 'completed', content }],
  );
}

function timelineRows(element: HTMLElement): HTMLElement[] {
  return [
    ...element.querySelectorAll<HTMLElement>(
      '.messages > .history-item > ai-chat-history-item > .collapse > .clip > .item-content > *',
    ),
  ];
}

function isCollapsed(element: HTMLElement): boolean {
  return (
    element
      .closest('ai-chat-history-item')
      ?.querySelector('.collapse')
      ?.getAttribute('aria-hidden') === 'true'
  );
}
