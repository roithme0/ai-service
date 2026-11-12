/* eslint-disable @typescript-eslint/unbound-method */
import {
  HttpImageGenerationTransport,
  ImageGenerationController,
} from '@roithme0/image-generation/controller';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { afterEach, expect, it, vi } from 'vitest';
import type {
  CompletedSnapshot,
  ImageContent,
  ImageGenerationState,
} from '@roithme0/image-generation/controller';
import {
  ImageGenerationUiComponent,
  type ImageGenerationActions,
  type ImageGenerationPrimaryAction,
} from './components/image-generation/image-generation.component';

const snapshot: CompletedSnapshot = {
  generation_id: 'one',
  status: 'completed',
  created_at: '2026-01-01',
  completed_at: '2026-01-01',
  configured_model: 'configured',
  provider_model: null,
  estimated_cost_usd: '0',
  content: { media_type: 'image/png', size_bytes: 1, url: '/private' },
};
const initial: ImageGenerationState = {
  admission: 'idle',
  instructions: null,
  snapshot: null,
  observation: 'idle',
  content: 'idle',
  error: null,
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function setup(
  loadContent: ImageGenerationActions['loadContent'] = vi.fn(() =>
    Promise.resolve({
      blob: new Blob(['png'], { type: 'image/png' }),
      filename: 'one.png',
      snapshot,
    }),
  ),
  mode: 'editable' | 'hidden' = 'editable',
) {
  const actions: ImageGenerationActions = {
    submit: vi.fn(async () => {}),
    recoverSubmission: vi.fn(async () => {}),
    reconnect: vi.fn(),
    loadContent,
  };
  const snackbar = { open: vi.fn() };
  TestBed.configureTestingModule({
    imports: [ImageGenerationUiComponent],
    providers: [{ provide: MatSnackBar, useValue: snackbar }],
  });
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', initial);
  fixture.componentRef.setInput('actions', actions);
  fixture.componentRef.setInput('instructionMode', mode);
  fixture.detectChanges();
  const root = fixture.nativeElement as HTMLElement;
  const setState = (state: ImageGenerationState) => {
    fixture.componentRef.setInput('state', state);
    fixture.detectChanges();
  };
  const button = (label: string) => {
    const found = [...root.querySelectorAll('button')].find(
      (item) => item.textContent?.trim() === label || item.getAttribute('aria-label') === label,
    );
    if (!found) throw new Error(`Missing ${label}`);
    return found;
  };
  const edit = (text: string) => {
    const textarea = root.querySelector('textarea')!;
    textarea.value = text;
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  };
  return { fixture, root, actions, setState, button, edit, snackbar };
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('validates code points and submits exact instructions once while pending', async () => {
  const pending = deferred<void>();
  const t = setup();
  vi.mocked(t.actions.submit).mockReturnValue(pending.promise);
  expect(t.button('Bild erstellen').disabled).toBe(true);
  t.edit('  ');
  expect(t.button('Bild erstellen').disabled).toBe(true);
  t.button('Bild erstellen').click();
  t.fixture.detectChanges();
  expect(t.actions.submit).not.toHaveBeenCalled();
  t.edit('\u{1F600}'.repeat(32001));
  expect(t.button('Bild erstellen').disabled).toBe(false);
  t.button('Bild erstellen').click();
  expect(t.actions.submit).not.toHaveBeenCalled();
  const text = `  ${'\u{1F600}'.repeat(31996)}  `;
  t.edit(text);
  t.button('Bild erstellen').click();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('Anfrage wird gesendet');
  expect(t.actions.submit).toHaveBeenCalledExactlyOnceWith(text);
  pending.resolve();
  await pending.promise;
});

it('keeps successful content and instructions through refinement and back without submitting', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const t = setup();
  t.setState({ ...initial, admission: 'accepted', instructions: 'original', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.actions.loadContent).toHaveBeenCalledOnce();
  expect(t.root.textContent).toContain('$0');
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('original');
  t.edit('edited');
  t.button('Zurück zum Ergebnis').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('img')?.getAttribute('src')).toBe('blob:owned');
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('edited');
  expect(t.actions.submit).not.toHaveBeenCalled();
  t.fixture.destroy();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned');
});

it('rejects mismatched content and retries only content', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const valid: ImageContent = {
    blob: new Blob(['png'], { type: 'image/png' }),
    filename: 'one.png',
    snapshot,
  };
  const load = vi
    .fn()
    .mockResolvedValueOnce({ ...valid, snapshot: { ...snapshot, generation_id: 'other' } })
    .mockResolvedValueOnce(valid);
  const t = setup(load);
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('configured');
  t.button('Bild erneut laden').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(load).toHaveBeenCalledTimes(2);
  expect(t.root.querySelector('img')?.getAttribute('src')).toBe('blob:owned');
  expect(t.actions.submit).not.toHaveBeenCalled();
});

it('switches from refinement to an externally supplied new result', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const second = { ...snapshot, generation_id: 'two' };
  const load = vi
    .fn()
    .mockResolvedValueOnce({
      blob: new Blob(['a'], { type: 'image/png' }),
      filename: 'one.png',
      snapshot,
    })
    .mockResolvedValueOnce({
      blob: new Blob(['b'], { type: 'image/png' }),
      filename: 'two.png',
      snapshot: second,
    });
  const t = setup(load);
  t.setState({ ...initial, admission: 'accepted', instructions: 'first', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.edit('draft');
  t.setState({ ...initial, admission: 'accepted', instructions: 'second', snapshot: second });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('Ihr Bild');
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('second');
});

it('ignores an obsolete recovery rejection while a new action is pending', async () => {
  let reject!: (error: Error) => void;
  const old = new Promise<void>((_resolve, fail) => {
    reject = fail;
  });
  const current = deferred<void>();
  const t = setup();
  vi.mocked(t.actions.recoverSubmission)
    .mockReturnValueOnce(old)
    .mockReturnValueOnce(current.promise);
  t.setState({ ...initial, admission: 'uncertain', instructions: 'first' });
  t.button('Anfrage wiederherstellen').click();
  t.fixture.detectChanges();
  t.setState({
    ...initial,
    admission: 'accepted',
    instructions: 'new',
    snapshot: {
      generation_id: 'new',
      status: 'running',
      created_at: '2026-01-01',
      completed_at: null,
      configured_model: 'configured',
      provider_model: null,
      estimated_cost_usd: null,
    },
  });
  t.setState({ ...initial, admission: 'uncertain', instructions: 'new' });
  t.button('Anfrage wiederherstellen').click();
  t.fixture.detectChanges();
  reject(new Error('obsolete'));
  await Promise.resolve();
  await Promise.resolve();
  t.fixture.detectChanges();
  expect(t.root.textContent).not.toContain('Die Anfrage konnte nicht wiederhergestellt werden.');
  expect(t.button('Anfrage wiederherstellen').disabled).toBe(true);
  current.resolve();
  await current.promise;
});

it('retains instructions and available metadata on confirmed failure', () => {
  const t = setup();
  const failed = {
    generation_id: 'failed',
    status: 'failed' as const,
    created_at: '2026-01-01',
    completed_at: '2026-01-01',
    configured_model: 'configured',
    provider_model: 'provider',
    estimated_cost_usd: '0.001',
    error: {
      kind: 'image_generation_failed' as const,
      detail: 'Erstellung fehlgeschlagen safely',
    },
  };
  t.setState({ ...initial, admission: 'accepted', instructions: 'failed brief', snapshot: failed });
  expect(t.root.textContent).toContain('Erstellung fehlgeschlagen');
  expect(t.root.textContent).not.toContain('Erstellung fehlgeschlagen safely');
  expect(t.root.textContent).toContain('provider');
  expect(t.root.textContent).toContain('0.001');
  expect(t.button('Beschreibung bearbeiten').classList.contains('mat-tonal-button')).toBe(true);
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('failed brief');
});

it('wires the supplied controller and owner-aware HTTP transport through uncertain recovery', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const id = 'b1e807b2-2824-4f9d-967b-1cd58a20c117';
  const completed = {
    ...snapshot,
    generation_id: id,
    created_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
  };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockRejectedValueOnce(new Error('lost'))
    .mockResolvedValueOnce(
      new Response(JSON.stringify(completed), {
        status: 202,
        headers: { 'content-type': 'application/json' },
      }),
    )
    .mockResolvedValueOnce(
      new Response(new Blob(['png'], { type: 'image/png' }), {
        status: 200,
        headers: { 'content-type': 'image/png' },
      }),
    );
  const t = setup();
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('/api/v1', 'owner', fetcher),
    (state) => t.fixture.componentRef.setInput('state', { ...state }),
  );
  t.fixture.componentRef.setInput('actions', {
    submit: (text: string) => controller.submit(text),
    recoverSubmission: () => controller.recoverSubmission(),
    reconnect: () => controller.reconnect(),
    loadContent: () => controller.loadContent(),
  });
  t.fixture.detectChanges();
  t.edit('exact brief');
  t.button('Bild erstellen').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  await vi.waitFor(() => {
    t.fixture.detectChanges();
    expect(t.root.textContent).toContain('Das Absenden konnte nicht bestätigt werden');
  });
  t.button('Anfrage wiederherstellen').click();
  await vi.waitFor(() => {
    t.fixture.detectChanges();
    expect(controller.state).toMatchObject({ admission: 'accepted' });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(fetcher).toHaveBeenCalledTimes(3);
  const first = fetcher.mock.calls[0][1]!;
  const second = fetcher.mock.calls[1][1]!;
  const content = fetcher.mock.calls[2][1]!;
  expect(first.body).toBe(second.body);
  expect(new Headers(first.headers).get('Idempotency-Key')).toBe(
    new Headers(second.headers).get('Idempotency-Key'),
  );
  expect(new Headers(content.headers).get('X-Application-User')).toBe('owner');
  expect(t.root.querySelector('img')?.getAttribute('src')).toBe('blob:owned');
  controller.dispose();
  t.fixture.destroy();
});

it('keeps Zurück zum Ergebnis available while completed content is pending or failed', async () => {
  const loading = deferred<ImageContent>();
  const t = setup(() => loading.promise);
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.button('Zurück zum Ergebnis').click();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('configured');
  loading.resolve({ blob: new Blob([], { type: 'image/png' }), filename: 'one.png', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.button('Zurück zum Ergebnis').click();
  t.fixture.detectChanges();
  expect(t.button('Bild erneut laden')).toBeTruthy();
  expect(t.actions.submit).not.toHaveBeenCalled();
});

it('associates labels and validation errors independently across instances', () => {
  const a = setup();
  const fixture = TestBed.createComponent(ImageGenerationUiComponent);
  fixture.componentRef.setInput('state', initial);
  fixture.componentRef.setInput('actions', a.actions);
  fixture.detectChanges();
  const root = fixture.nativeElement as HTMLElement;
  a.edit('x'.repeat(32001));
  const secondInput = root.querySelector('textarea')!;
  secondInput.value = 'x'.repeat(32001);
  secondInput.dispatchEvent(new Event('input'));
  fixture.detectChanges();
  a.button('Bild erstellen').click();
  root.querySelector('button')!.click();
  a.fixture.detectChanges();
  fixture.detectChanges();
  const first = a.root.querySelector('textarea')!;
  const second = root.querySelector('textarea')!;
  expect(first.id).not.toBe(second.id);
  expect(first.getAttribute('aria-label')).toBe('Beschreibung');
  expect(second.getAttribute('aria-label')).toBe('Beschreibung');
  expect(first.getAttribute('aria-describedby')).not.toBe(second.getAttribute('aria-describedby'));
});

it('retries invalid media and decoded-image errors without regeneration', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const valid: ImageContent = {
    blob: new Blob(['png'], { type: 'image/png' }),
    filename: 'one.png',
    snapshot,
  };
  const load = vi
    .fn()
    .mockResolvedValueOnce({ ...valid, blob: new Blob(['bad'], { type: 'image/jpeg' }) })
    .mockResolvedValue(valid);
  const t = setup(load);
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Bild erneut laden').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.root.querySelector('img')!.dispatchEvent(new Event('error'));
  t.fixture.detectChanges();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned');
  t.button('Bild erneut laden').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(load).toHaveBeenCalledTimes(3);
  expect(t.actions.submit).not.toHaveBeenCalled();
  expect(t.root.querySelector('img')).toBeTruthy();
});

it('ignores stale content when explicit new generation replaces a completed result', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const old = deferred<ImageContent>();
  const t = setup(() => old.promise);
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.edit('new brief');
  t.button('Bild erstellen').click();
  t.fixture.detectChanges();
  old.resolve({ blob: new Blob(['png'], { type: 'image/png' }), filename: 'one.png', snapshot });
  await old.promise;
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(t.root.querySelector('img')).toBeNull();
  expect(t.actions.submit).toHaveBeenCalledExactlyOnceWith('new brief');
});

it('passes the retained payload to handoff once and stays on success after fulfillment', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const pending = deferred<void>();
  const run = vi.fn<ImageGenerationPrimaryAction['run']>(() => pending.promise);
  const t = setup();
  t.fixture.componentRef.setInput('primaryAction', { label: 'Use image', run });
  t.setState({ ...initial, admission: 'accepted', instructions: 'exact brief', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Use image').click();
  t.fixture.detectChanges();
  t.button('Use image').click();
  expect(run).toHaveBeenCalledOnce();
  expect(run.mock.calls[0][0]).toMatchObject({
    filename: 'one.png',
    snapshot,
    instructions: 'exact brief',
  });
  expect(run.mock.calls[0][0].blob).toBeInstanceOf(Blob);
  expect(t.button('PNG herunterladen').disabled).toBe(true);
  expect(t.button('Beschreibung bearbeiten').disabled).toBe(true);
  pending.resolve();
  await pending.promise;
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('Ihr Bild');
});

it('reports handoff failure and ignores obsolete handoff rejection on replacement', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const second = { ...snapshot, generation_id: 'two' };
  const third = { ...snapshot, generation_id: 'three' };
  const load = vi
    .fn()
    .mockResolvedValueOnce({
      blob: new Blob(['a'], { type: 'image/png' }),
      filename: 'one.png',
      snapshot,
    })
    .mockResolvedValueOnce({
      blob: new Blob(['b'], { type: 'image/png' }),
      filename: 'two.png',
      snapshot: second,
    })
    .mockResolvedValueOnce({
      blob: new Blob(['c'], { type: 'image/png' }),
      filename: 'three.png',
      snapshot: third,
    });
  let reject!: (error: Error) => void;
  const late = new Promise<void>((_done, fail) => {
    reject = fail;
  });
  const run = vi.fn().mockRejectedValueOnce(new Error('host failure')).mockReturnValueOnce(late);
  const t = setup(load);
  t.fixture.componentRef.setInput('primaryAction', { label: 'Use image', run });
  t.setState({ ...initial, admission: 'accepted', instructions: 'first', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Use image').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.snackbar.open).toHaveBeenCalledOnce();
  expect(t.snackbar.open).toHaveBeenCalledWith(
    'Die Aktion ist fehlgeschlagen. Bitte versuchen Sie es erneut.',
    'OK',
    {
      duration: 6000,
      politeness: 'assertive',
    },
  );
  t.setState({ ...initial, admission: 'accepted', instructions: 'second', snapshot: second });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Use image').click();
  t.fixture.detectChanges();
  t.setState({ ...initial, admission: 'accepted', instructions: 'third', snapshot: third });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  reject(new Error('late'));
  await Promise.resolve();
  await Promise.resolve();
  t.fixture.detectChanges();
  expect(t.snackbar.open).toHaveBeenCalledOnce();
  expect(t.button('Use image').disabled).toBe(false);
});

it('keeps a synchronously published matching submission pending until its callback settles', async () => {
  const t = setup();
  const pending = deferred<void>();
  vi.mocked(t.actions.submit).mockImplementation((instructions) => {
    t.setState({ ...initial, admission: 'accepted', instructions, snapshot });
    return pending.promise;
  });

  t.edit('brief');
  t.button('Bild erstellen').click();
  t.fixture.detectChanges();
  expect(t.fixture.componentInstance.actionCoordinator.pending()).toBe(true);

  pending.resolve();
  await pending.promise;
  await Promise.resolve();
  expect(t.fixture.componentInstance.actionCoordinator.pending()).toBe(false);
});

it('preserves the brief on authoritative rejection and does not invent a failure on callback throw', async () => {
  const t = setup();
  vi.mocked(t.actions.submit).mockImplementation(() => {
    t.setState({ ...initial, admission: 'uncertain', instructions: 'exact brief' });
    return Promise.reject(new Error('network'));
  });
  t.edit('exact brief');
  t.button('Bild erstellen').click();
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.root.textContent).toContain('Das Absenden konnte nicht bestätigt werden');
  expect(t.root.textContent).not.toContain('Erstellung fehlgeschlagen');
  t.setState({
    ...initial,
    admission: 'rejected',
    instructions: 'exact brief',
    error: 'Rejected by service',
  });
  expect(t.root.textContent).toContain('Rejected by service');
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('exact brief');
});

it('ignores content settling after destruction without creating a URL', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const late = deferred<ImageContent>();
  const t = setup(() => late.promise);
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  t.fixture.destroy();
  late.resolve({ blob: new Blob(['png'], { type: 'image/png' }), filename: 'one.png', snapshot });
  await late.promise;
  await Promise.resolve();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it('reconnects a lost controller observation to the same ID without another submission', async () => {
  const id = 'b1e807b2-2824-4f9d-967b-1cd58a20c117';
  const running = {
    generation_id: id,
    status: 'running',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    configured_model: 'model',
    provider_model: null,
    estimated_cost_usd: null,
  };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json(running, { status: 202 }))
    .mockImplementation(() =>
      Promise.resolve(new Response('', { headers: { 'content-type': 'text/event-stream' } })),
    );
  const t = setup();
  const controller = new ImageGenerationController(
    new HttpImageGenerationTransport('/api/v1', 'owner', fetcher),
    (state) => t.fixture.componentRef.setInput('state', { ...state }),
  );
  t.fixture.componentRef.setInput('actions', {
    submit: (text: string) => controller.submit(text),
    recoverSubmission: () => controller.recoverSubmission(),
    reconnect: () => controller.reconnect(),
    loadContent: () => controller.loadContent(),
  });
  t.fixture.detectChanges();
  t.edit('brief');
  t.button('Bild erstellen').click();
  await vi.waitFor(() => {
    t.fixture.detectChanges();
    expect(t.root.textContent).toContain('Erneut mit dem Status verbinden');
  });
  t.button('Erneut mit dem Status verbinden').click();
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  expect(fetcher.mock.calls[0][1]?.method).toBe('POST');
  expect(fetcher.mock.calls[1][0]).toBe(`/api/v1/image-generations/${id}/events`);
  expect(fetcher.mock.calls[2][0]).toBe(`/api/v1/image-generations/${id}/events`);
  controller.dispose();
  t.fixture.destroy();
});

it('ignores a handoff rejection after destruction', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  let reject!: (error: Error) => void;
  const late = new Promise<void>((_done, fail) => {
    reject = fail;
  });
  const t = setup();
  t.fixture.componentRef.setInput('primaryAction', { label: 'Use image', run: () => late });
  t.setState({ ...initial, admission: 'accepted', instructions: 'brief', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Use image').click();
  t.fixture.destroy();
  reject(new Error('late'));
  await Promise.resolve();
  await Promise.resolve();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned');
  expect(t.fixture.componentInstance.error()).toBeNull();
});

it('keeps hidden instructions absent and retries a direct rejection with exact instructions', () => {
  const t = setup(undefined, 'hidden');
  expect(t.root.querySelector('textarea')).toBeNull();
  expect(t.root.textContent).toContain('Bilderstellung wird vorbereitet');
  expect(t.actions.submit).not.toHaveBeenCalled();
  const instructions = '  Gr??e ??  ';
  t.setState({ ...initial, admission: 'rejected', instructions, error: 'Abgelehnt' });
  expect(t.root.querySelector('textarea')).toBeNull();
  expect(t.root.textContent).not.toContain(instructions);
  t.button('Erneut versuchen').click();
  t.button('Erneut versuchen').click();
  expect(t.actions.submit).toHaveBeenCalledExactlyOnceWith(instructions);
});

it.each(['editable', 'hidden'] as const)(
  'retains failed instructions and guards retry in %s mode',
  async (mode) => {
    const t = setup(undefined, mode);
    const pending = deferred<void>();
    vi.mocked(t.actions.submit).mockReturnValue(pending.promise);
    const instructions = '  Gr\u00fc\u00dfe \u{1F600}\n';
    const failed = {
      generation_id: 'failed',
      status: 'failed' as const,
      created_at: '2026-01-01',
      completed_at: '2026-01-01',
      configured_model: 'model',
      provider_model: null,
      estimated_cost_usd: null,
      error: { kind: 'image_generation_failed' as const, detail: 'failed' },
    };
    const state: ImageGenerationState = {
      ...initial,
      admission: 'accepted',
      instructions,
      snapshot: failed,
    };
    t.setState(state);
    if (mode === 'editable') {
      t.button('Beschreibung bearbeiten').click();
      t.fixture.detectChanges();
      expect(t.root.querySelector('textarea')?.value).toBe(instructions);
      t.edit('unsubmitted draft');
      t.setState({ ...state });
      expect(t.root.querySelector('textarea')?.value).toBe('unsubmitted draft');
      expect(t.actions.submit).not.toHaveBeenCalled();
      t.setState({ ...initial, admission: 'submitting', instructions });
      t.setState(state);
    } else {
      expect(t.root.querySelector('textarea')).toBeNull();
      expect(t.root.textContent).not.toContain(instructions);
      expect(t.root.textContent).not.toContain('Beschreibung bearbeiten');
    }
    t.button('Erneut versuchen').click();
    t.fixture.detectChanges();
    expect(t.actions.submit).toHaveBeenCalledExactlyOnceWith(instructions);
    expect(t.fixture.componentInstance.actionCoordinator.pending()).toBe(true);
    pending.resolve();
    await pending.promise;
  },
);

it.each(['editable', 'hidden'] as const)(
  'retains initial %s mode when the input changes',
  (mode) => {
    const t = setup(undefined, mode);
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    t.fixture.componentRef.setInput('instructionMode', mode === 'editable' ? 'hidden' : 'editable');
    t.fixture.detectChanges();
    expect(error).toHaveBeenCalled();
    expect(t.fixture.componentInstance.effectiveMode()).toBe(mode);
    expect(Boolean(t.root.querySelector('textarea'))).toBe(mode === 'editable');
  },
);

it('keeps a rejected edit usable across repeated state publication', () => {
  const t = setup();
  const instructions = '  \u{1F600} original  ';
  const state: ImageGenerationState = {
    ...initial,
    admission: 'rejected',
    instructions,
    error: 'Rejected',
  };
  t.setState(state);
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe(instructions);
  t.edit('draft');
  t.setState({ ...state });
  expect(t.root.querySelector('textarea')?.value).toBe('draft');
  expect(t.actions.submit).not.toHaveBeenCalled();
});

it('leaves error editing when an external attempt is rejected', () => {
  const t = setup();
  const rejected: ImageGenerationState = {
    ...initial,
    admission: 'rejected',
    instructions: 'first',
    error: 'Rejected',
  };
  t.setState(rejected);
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.setState({ ...initial, admission: 'submitting', instructions: 'second' });
  t.setState({ ...rejected, instructions: 'second' });
  expect(t.root.querySelector('textarea')).toBeNull();
  expect(t.root.textContent).toContain('Erneut versuchen');
});

it('keeps retry and edit disabled until the submitted action settles', () => {
  const t = setup();
  const pending = deferred<void>();
  vi.mocked(t.actions.submit).mockReturnValue(pending.promise);
  t.edit('brief');
  t.button('Bild erstellen').click();
  t.setState({
    ...initial,
    admission: 'accepted',
    instructions: 'brief',
    snapshot: {
      generation_id: 'new',
      status: 'failed',
      created_at: '2026-01-01',
      completed_at: '2026-01-01',
      configured_model: 'model',
      provider_model: null,
      estimated_cost_usd: null,
      error: { kind: 'image_generation_failed', detail: 'failed' },
    },
  });
  expect(t.button('Erneut versuchen').disabled).toBe(true);
  expect(t.button('Beschreibung bearbeiten').disabled).toBe(true);
  pending.resolve();
});

it('shows a replacement rejection when intermediate external submission is coalesced', () => {
  const t = setup();
  t.setState({ ...initial, admission: 'rejected', instructions: 'first', error: 'Rejected' });
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.fixture.componentRef.setInput('state', {
    ...initial,
    admission: 'submitting',
    instructions: 'second',
  });
  t.fixture.componentRef.setInput('state', {
    ...initial,
    admission: 'rejected',
    instructions: 'second',
    error: 'Rejected again',
  });
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')).toBeNull();
  expect(t.root.textContent).toContain('Rejected again');
});

it.each(['rejected', 'failed'] as const)(
  'retries %s through the real controller with a fresh key and completes',
  async (failure) => {
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
    const id = 'b1e807b2-2824-4f9d-967b-1cd58a20c117';
    const completed = {
      ...snapshot,
      generation_id: id,
      created_at: '2026-01-01T00:00:00Z',
      completed_at: '2026-01-01T00:00:01Z',
    };
    const failed = {
      ...completed,
      status: 'failed',
      content: undefined,
      error: { kind: 'image_generation_failed', detail: 'failed' },
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        failure === 'rejected'
          ? Response.json(
              { kind: 'image_generation_unavailable', detail: 'Unavailable' },
              { status: 503 },
            )
          : Response.json(failed, { status: 202 }),
      )
      .mockResolvedValueOnce(Response.json(completed, { status: 202 }))
      .mockResolvedValueOnce(
        new Response(new Blob(['png'], { type: 'image/png' }), {
          headers: { 'content-type': 'image/png' },
        }),
      );
    const t = setup(undefined, 'hidden');
    const controller = new ImageGenerationController(
      new HttpImageGenerationTransport('/api/v1', 'owner', fetcher),
      (state) => t.fixture.componentRef.setInput('state', { ...state }),
    );
    t.fixture.componentRef.setInput('actions', {
      submit: (text: string) => controller.submit(text),
      recoverSubmission: () => controller.recoverSubmission(),
      reconnect: () => controller.reconnect(),
      loadContent: () => controller.loadContent(),
    });
    const instructions = '  \u{1F600} exact  ';
    await controller.submit(instructions);
    t.fixture.detectChanges();
    t.button('Erneut versuchen').click();
    await vi.waitFor(() => {
      t.fixture.detectChanges();
      expect(t.root.querySelector('img')?.getAttribute('src')).toBe('blob:owned');
    });
    const first = fetcher.mock.calls[0][1]!;
    const second = fetcher.mock.calls[1][1]!;
    expect(first.body).toBe(second.body);
    expect(new Headers(first.headers).get('Idempotency-Key')).not.toBe(
      new Headers(second.headers).get('Idempotency-Key'),
    );
    controller.dispose();
    t.fixture.destroy();
  },
);

it('preserves hidden-mode result handoff and download', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const run = vi.fn<ImageGenerationPrimaryAction['run']>(() => Promise.resolve());
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const t = setup(undefined, 'hidden');
  t.fixture.componentRef.setInput('primaryAction', { label: 'Use image', run });
  t.setState({ ...initial, admission: 'accepted', instructions: 'exact brief', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  expect(t.root.textContent).not.toContain('Beschreibung bearbeiten');
  t.button('PNG herunterladen').click();
  expect(click).toHaveBeenCalledOnce();
  t.button('Use image').click();
  expect(run).toHaveBeenCalledOnce();
  expect(run.mock.calls[0][0]).toMatchObject({
    filename: 'one.png',
    snapshot,
    instructions: 'exact brief',
  });
  expect(run.mock.calls[0][0].blob).toBeInstanceOf(Blob);
});

it('models repeated rejection edits and coalesced replacement', async () => {
  const { applyControllerState, editInstructions, initialWorkflow } =
    await import('./components/image-generation/workflow');
  const rejected: ImageGenerationState = {
    ...initial,
    admission: 'rejected',
    instructions: 'first',
    error: 'Rejected',
  };
  const first = applyControllerState(initialWorkflow(), rejected, 'editable', null);
  const editing = { ...editInstructions(first.workflow, true), draft: 'draft' };
  const repeated = applyControllerState(editing, rejected, 'editable', null);
  expect(repeated.workflow).toMatchObject({
    activity: 'editing',
    draft: 'draft',
    submitted: 'first',
  });
  const replacement = applyControllerState(
    repeated.workflow,
    { ...rejected, instructions: 'second' },
    'editable',
    null,
  );
  expect(replacement.workflow).toMatchObject({
    activity: 'generating',
    submitted: 'second',
  });
});

it('preserves only the matching pending submission when a generation arrives', async () => {
  const { applyControllerState, initialWorkflow, startSubmission } =
    await import('./components/image-generation/workflow');
  const submitting = startSubmission(initialWorkflow(), 'brief');
  const matching = applyControllerState(
    submitting,
    { ...initial, admission: 'accepted', instructions: 'brief', snapshot },
    'editable',
    'brief',
  );
  expect(matching).toMatchObject({ clearResult: true, preserveAction: true, loadContent: true });
  const replacement = applyControllerState(
    matching.workflow,
    {
      ...initial,
      admission: 'accepted',
      instructions: 'other',
      snapshot: { ...snapshot, generation_id: 'two' },
    },
    'editable',
    'brief',
  );
  expect(replacement).toMatchObject({
    clearResult: true,
    preserveAction: false,
    loadContent: true,
  });
});

it('retains refinement intent when a transient uncertain state hides the editor', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const t = setup();
  const completed: ImageGenerationState = {
    ...initial,
    admission: 'accepted',
    instructions: 'brief',
    snapshot,
  };
  t.setState(completed);
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.edit('draft');
  t.setState({ ...completed, admission: 'uncertain' });
  expect(t.root.querySelector('textarea')).toBeNull();
  t.setState(completed);
  expect(t.root.querySelector('textarea')).toBeNull();
  expect(t.root.textContent).not.toContain('Ihr Bild');
});

it('retains rejection editing across an idle publication', () => {
  const t = setup();
  const rejected: ImageGenerationState = {
    ...initial,
    admission: 'rejected',
    instructions: 'brief',
    error: 'Rejected',
  };
  t.setState(rejected);
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.edit('draft');
  t.setState(initial);
  t.setState(rejected);
  expect(t.root.querySelector('textarea')?.value).toBe('draft');
});

it('retains an empty refinement across back and edit again', async () => {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:owned'), revokeObjectURL: vi.fn() });
  const t = setup();
  t.setState({ ...initial, admission: 'accepted', instructions: 'original', snapshot });
  await t.fixture.whenStable();
  t.fixture.detectChanges();
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  t.edit('');
  t.button('Zurück zum Ergebnis').click();
  t.fixture.detectChanges();
  t.button('Beschreibung bearbeiten').click();
  t.fixture.detectChanges();
  expect(t.root.querySelector('textarea')?.value).toBe('');
});
