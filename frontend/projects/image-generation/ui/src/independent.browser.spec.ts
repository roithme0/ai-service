import type {} from '@vitest/browser-playwright';
/* eslint-disable @typescript-eslint/unbound-method */
import { TestBed } from '@angular/core/testing';
import { expect, it, vi } from 'vitest';
import { cdp, page, userEvent } from 'vitest/browser';
import type { ImageGenerationState } from '@roithme0/image-generation/controller';
import {
  ImageGenerationUiComponent,
  type ImageGenerationActions,
} from './components/image-generation/image-generation.component';

it('supports native textarea and keyboard activation in a narrow host', async () => {
  const state: ImageGenerationState = {
    admission: 'idle',
    instructions: null,
    snapshot: null,
    observation: 'idle',
    content: 'idle',
    error: null,
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('actions', actions);
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '320px';
  host.style.height = '400px';
  host.style.setProperty('--ai-ui-composer-background', 'rgb(12, 34, 56)');
  host.style.setProperty('--ai-ui-composer-border', 'rgb(65, 43, 21)');
  fixture.detectChanges();
  await fixture.whenStable();
  const input = page.getByRole('textbox', { name: 'Beschreibung' });
  const textarea = input.element() as HTMLTextAreaElement;
  const surface = textarea.parentElement!;
  expect(getComputedStyle(surface).backgroundColor).toBe('rgb(12, 34, 56)');
  expect(getComputedStyle(surface).borderColor).toBe('rgb(65, 43, 21)');
  const lineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight);
  const contentHeight = (): number => {
    const style = getComputedStyle(textarea);
    return (
      textarea.clientHeight -
      Number.parseFloat(style.paddingTop) -
      Number.parseFloat(style.paddingBottom)
    );
  };
  expect(contentHeight()).toBeCloseTo(lineHeight * 3, 0);
  expect(getComputedStyle(textarea).resize).toBe('none');
  await input.fill(Array.from({ length: 6 }, () => 'line').join('\n'));
  await expect.poll(contentHeight).toBeCloseTo(lineHeight * 6, 0);
  await input.fill(Array.from({ length: 12 }, () => 'line').join('\n'));
  await expect.poll(contentHeight).toBeCloseTo(lineHeight * 10, 0);
  expect(textarea.scrollHeight).toBeGreaterThan(textarea.clientHeight);
  await input.fill('first');
  await expect.poll(contentHeight).toBeCloseTo(lineHeight * 3, 0);
  const generateBounds = page
    .getByRole('button', { name: 'Bild erstellen' })
    .element()
    .getBoundingClientRect();
  expect(generateBounds.bottom).toBeLessThanOrEqual(host.getBoundingClientRect().bottom);
  await userEvent.keyboard('{Enter}second');
  await expect.element(input).toHaveValue('first\nsecond');
  expect(actions.submit).not.toHaveBeenCalled();
  const button = page.getByRole('button', { name: 'Bild erstellen' });
  button.element().focus();
  await userEvent.keyboard('{Enter}');
  expect(actions.submit).toHaveBeenCalledExactlyOnceWith('first\nsecond');
  await expect.element(page.getByRole('heading', { name: 'Bild wird erstellt' })).toBeVisible();
  await expect.poll(() => document.activeElement?.textContent?.trim()).toBe('Bild wird erstellt');
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
});

it('renders state transitions, focus and reflow in a real browser', async () => {
  const idle: ImageGenerationState = {
    admission: 'idle',
    instructions: null,
    snapshot: null,
    observation: 'idle',
    content: 'idle',
    error: null,
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', idle);
  fixture.componentRef.setInput('actions', actions);
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '100%';
  host.style.height = '100%';
  fixture.detectChanges();
  for (const [name, state] of [
    ['input', idle],
    ['submitting', { ...idle, admission: 'submitting' as const, instructions: 'Brief' }],
    ['uncertain', { ...idle, admission: 'uncertain' as const, instructions: 'Brief' }],
    [
      'running',
      {
        ...idle,
        admission: 'accepted' as const,
        instructions: 'Brief',
        snapshot: {
          status: 'running' as const,
          generation_id: 'one',
          created_at: '2026-01-01',
          completed_at: null,
          configured_model: 'model',
          provider_model: null,
          estimated_cost_usd: null,
        },
      },
    ],
    [
      'lost',
      {
        ...idle,
        admission: 'accepted' as const,
        instructions: 'Brief',
        observation: 'lost' as const,
        snapshot: {
          status: 'running' as const,
          generation_id: 'one',
          created_at: '2026-01-01',
          completed_at: null,
          configured_model: 'model',
          provider_model: null,
          estimated_cost_usd: null,
        },
      },
    ],
    [
      'failure',
      {
        ...idle,
        admission: 'accepted' as const,
        instructions: 'Brief',
        snapshot: {
          status: 'failed' as const,
          generation_id: 'one',
          created_at: '2026-01-01',
          completed_at: '2026-01-01',
          configured_model: 'model',
          provider_model: null,
          estimated_cost_usd: null,
          error: {
            kind: 'image_generation_failed' as const,
            detail: 'Bilderstellung fehlgeschlagen',
          },
        },
      },
    ],
  ] as const) {
    fixture.componentRef.setInput('state', state);
    fixture.detectChanges();
    await fixture.whenStable();
    const expected: Record<string, string> = {
      input: 'Bild erstellen',
      submitting: 'Anfrage wird gesendet',
      uncertain: 'Anfrage wiederherstellen',
      running: 'Bild wird erstellt',
      lost: 'Erneut mit dem Status verbinden',
      failure: 'Bilderstellung fehlgeschlagen',
    };
    expect(host.textContent).toContain(expected[name]);
    await page.screenshot({ path: '../../test-results/' + name + '.png' });
    expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
  }
  await expect
    .poll(() => document.activeElement?.textContent?.trim())
    .toBe('Bilderstellung fehlgeschlagen');
  await page.viewport(320, 400);
  fixture.detectChanges();
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
  const refine = page.getByRole('button', { name: 'Beschreibung bearbeiten' });
  await expect.element(refine).toBeVisible();
  await refine.click();
  await expect.poll(() => document.activeElement?.tagName).toBe('TEXTAREA');
  await page.screenshot({ path: '../../test-results/refinement.png' });
});

it('shows a decoded image and retains focus while content settles and handoff fails', async () => {
  const snapshot = {
    status: 'completed' as const,
    generation_id: 'one',
    created_at: '2026-01-01',
    completed_at: '2026-01-01',
    configured_model: 'model',
    provider_model: null,
    estimated_cost_usd: null,
    content: { media_type: 'image/png' as const, size_bytes: 68, url: '/private' },
  };
  const state: ImageGenerationState = {
    admission: 'accepted',
    instructions: 'Brief',
    snapshot,
    observation: 'idle',
    content: 'idle',
    error: null,
  };
  const canvas = document.createElement('canvas');
  canvas.width = 120;
  canvas.height = 60;
  const context = canvas.getContext('2d')!;
  context.fillStyle = '#e86330';
  context.fillRect(0, 0, 120, 60);
  const png = await new Promise<Blob>((done, fail) =>
    canvas.toBlob(
      (blob) => (blob ? done(blob) : fail(new Error('PNG encoding failed'))),
      'image/png',
    ),
  );
  let resolve!: (value: { blob: Blob; filename: string; snapshot: typeof snapshot }) => void;
  const content = new Promise<{ blob: Blob; filename: string; snapshot: typeof snapshot }>(
    (done) => {
      resolve = done;
    },
  );
  let reject!: (reason: Error) => void;
  const handoff = new Promise<void>((_done, fail) => {
    reject = fail;
  });
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: () => content,
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('actions', actions);
  fixture.componentRef.setInput('primaryAction', { label: 'Use image', run: () => handoff });
  fixture.detectChanges();
  await page.screenshot({ path: '../../test-results/content-loading.png' });
  const refine = page.getByRole('button', { name: 'Beschreibung bearbeiten' });
  await refine.click();
  await expect.poll(() => document.activeElement?.tagName).toBe('TEXTAREA');
  resolve({ blob: png, filename: 'one.png', snapshot });
  await fixture.whenStable();
  fixture.detectChanges();
  expect(document.activeElement?.tagName).toBe('TEXTAREA');
  await page.getByRole('button', { name: 'Zurück zum Ergebnis' }).click();
  await expect.poll(() => document.activeElement?.textContent?.trim()).toBe('Ihr Bild');
  const img = page.getByRole('img', { name: 'Erstelltes Bild' });
  await expect.element(img).toBeVisible();
  await expect.poll(() => (img.element() as HTMLImageElement).naturalWidth).toBe(120);
  const bounds = img.element().getBoundingClientRect();
  expect(bounds.width).toBeGreaterThan(0);
  expect(bounds.height).toBeGreaterThan(0);
  expect(bounds.width / bounds.height).toBeCloseTo(2, 1);
  await page.screenshot({ path: '../../test-results/success.png' });
  await page.viewport(320, 400);
  const shortBounds = img.element().getBoundingClientRect();
  expect(shortBounds.width).toBeGreaterThan(0);
  expect(shortBounds.height).toBeGreaterThan(0);
  expect(shortBounds.width / shortBounds.height).toBeCloseTo(2, 1);
  await page.getByRole('button', { name: 'Use image' }).click();
  fixture.detectChanges();
  await expect.element(page.getByRole('button', { name: 'PNG herunterladen' })).toBeDisabled();
  await page.screenshot({ path: '../../test-results/handoff-pending.png' });
  reject(new Error('failed'));
  await fixture.whenStable();
  fixture.detectChanges();
  await expect
    .element(page.getByText('Die Aktion ist fehlgeschlagen. Bitte versuchen Sie es erneut.'))
    .toBeVisible();
  await page.screenshot({ path: '../../test-results/handoff-error.png' });
  const session = cdp();
  await session.send('Browser.setDownloadBehavior', {
    behavior: 'default',
    eventsEnabled: true,
  });
  let startListener!: (event: { guid: string; suggestedFilename: string }) => void;
  const started = new Promise<{ guid: string; suggestedFilename: string }>((done) => {
    startListener = done;
    session.on('Browser.downloadWillBegin', startListener);
  });
  let finishListener!: (event: { guid: string; state: string }) => void;
  const finished = new Promise<{ guid: string; state: string }>((done) => {
    finishListener = (event) => {
      if (event.state === 'completed') done(event);
    };
    session.on('Browser.downloadProgress', finishListener);
  });
  await page.getByRole('button', { name: 'PNG herunterladen' }).click();
  const download = await started;
  const progress = await finished;
  expect(download.suggestedFilename).toBe('one.png');
  expect(progress.guid).toBe(download.guid);
  session.off('Browser.downloadWillBegin', startListener);
  session.off('Browser.downloadProgress', finishListener);
});

it('keeps long errors and actions reachable in landscape and enlarged text', async () => {
  await page.viewport(844, 390);
  const state: ImageGenerationState = {
    admission: 'accepted',
    instructions: 'Brief',
    observation: 'idle',
    content: 'idle',
    error: null,
    snapshot: {
      status: 'failed',
      generation_id: 'one',
      created_at: '2026-01-01',
      completed_at: '2026-01-01',
      configured_model: 'long'.repeat(100),
      provider_model: null,
      estimated_cost_usd: null,
      error: { kind: 'image_generation_failed', detail: 'error'.repeat(100) },
    },
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('actions', actions);
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '100%';
  host.style.height = '100%';
  host.style.fontSize = '24px';
  fixture.detectChanges();
  await fixture.whenStable();
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
  await expect.element(page.getByRole('button', { name: 'Beschreibung bearbeiten' })).toBeVisible();
  await page.screenshot({ path: '../../test-results/landscape-long-error.png' });
});

it('shows content-only retry with completed metadata after load failure', async () => {
  const state: ImageGenerationState = {
    admission: 'accepted',
    instructions: 'Brief',
    observation: 'idle',
    content: 'idle',
    error: null,
    snapshot: {
      status: 'completed',
      generation_id: 'one',
      created_at: '2026-01-01',
      completed_at: '2026-01-01',
      configured_model: 'model',
      provider_model: null,
      estimated_cost_usd: null,
      content: { media_type: 'image/png', size_bytes: 1, url: '/private' },
    },
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(() => Promise.reject(new Error('content'))),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('actions', actions);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  await expect.element(page.getByRole('button', { name: 'Bild erneut laden' })).toBeVisible();
  const placeholder = (fixture.nativeElement as HTMLElement).querySelector(
    'ai-image-generation-image-placeholder',
  )!;
  expect(placeholder.querySelector('[role="alert"]')?.textContent).toContain(
    'Das Bild konnte nicht geladen werden.',
  );
  expect(placeholder.querySelector('button')?.textContent).toContain('Bild erneut laden');
  expect(placeholder.querySelector('rect')).not.toBeNull();
  expect((fixture.nativeElement as HTMLElement).textContent).toContain('model');
  await page.screenshot({ path: '../../test-results/content-error.png' });
});

it('keeps hidden mode free of editing and supports rejection retry by keyboard in a short portrait host', async () => {
  await page.viewport(320, 400);
  const idle: ImageGenerationState = {
    admission: 'idle',
    instructions: null,
    snapshot: null,
    observation: 'idle',
    content: 'idle',
    error: null,
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', idle);
  fixture.componentRef.setInput('actions', actions);
  fixture.componentRef.setInput('instructionMode', 'hidden');
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '320px';
  host.style.height = '400px';
  fixture.detectChanges();
  expect(host.querySelector('textarea')).toBeNull();
  expect(host.textContent).toContain('Bilderstellung wird vorbereitet');
  expect(actions.submit).not.toHaveBeenCalled();
  fixture.componentRef.setInput('state', {
    ...idle,
    admission: 'rejected',
    instructions: 'private brief',
    error: 'Abgelehnt',
  });
  fixture.detectChanges();
  await fixture.whenStable();
  expect(host.querySelector('textarea')).toBeNull();
  expect(host.textContent).not.toContain('private brief');
  expect(document.activeElement?.tagName).not.toBe('TEXTAREA');
  const retry = page.getByRole('button', { name: 'Erneut versuchen' });
  await expect.element(retry).toBeVisible();
  retry.element().focus();
  await userEvent.keyboard('{Enter}');
  expect(actions.submit).toHaveBeenCalledExactlyOnceWith('private brief');
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
});

it('keeps hidden failure retry reachable and keyboard operable in portrait', async () => {
  await page.viewport(320, 400);
  const state: ImageGenerationState = {
    admission: 'accepted',
    instructions: 'brief',
    observation: 'idle',
    content: 'idle',
    error: null,
    snapshot: {
      generation_id: 'failed',
      status: 'failed',
      created_at: '2026-01-01',
      completed_at: '2026-01-01',
      configured_model: 'model',
      provider_model: null,
      estimated_cost_usd: null,
      error: { kind: 'image_generation_failed', detail: 'failed' },
    },
  };
  const actions: ImageGenerationActions = {
    submit: vi.fn(() => Promise.resolve()),
    recoverSubmission: vi.fn(() => Promise.resolve()),
    reconnect: vi.fn(),
    loadContent: vi.fn(),
  };
  TestBed.configureTestingModule({ imports: [ImageGenerationUiComponent] });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', state);
  fixture.componentRef.setInput('actions', actions);
  fixture.componentRef.setInput('instructionMode', 'hidden');
  const host = fixture.nativeElement as HTMLElement;
  host.style.width = '320px';
  host.style.height = '400px';
  fixture.detectChanges();
  await fixture.whenStable();
  expect(host.querySelector('textarea')).toBeNull();
  expect(host.textContent).not.toContain('Beschreibung bearbeiten');
  await expect
    .poll(() => document.activeElement?.textContent?.trim())
    .toBe('Bilderstellung fehlgeschlagen');
  const retry = page.getByRole('button', { name: 'Erneut versuchen' });
  await expect.element(retry).toBeVisible();
  retry.element().focus();
  await userEvent.keyboard('{Enter}');
  expect(actions.submit).toHaveBeenCalledExactlyOnceWith('brief');
  expect(host.scrollWidth).toBeLessThanOrEqual(host.clientWidth);
});
