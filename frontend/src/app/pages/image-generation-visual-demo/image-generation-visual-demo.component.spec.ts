import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ImageGenerationUiComponent } from '@roithme0/image-generation/ui';
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest';
import { ImageGenerationVisualDemo } from './image-generation-visual-demo.component';
import { ImageGenerationVisualTransport } from './image-generation-visual-transport';

const payload = {
  instructions: 'draw',
  blob: new Blob(),
  filename: 'demo-image.png',
  snapshot: {
    generation_id: 'demo',
    status: 'completed' as const,
    created_at: '2026-01-01T00:00:00Z',
    completed_at: '2026-01-01T00:00:01Z',
    configured_model: 'Demo model',
    provider_model: null,
    estimated_cost_usd: '0.00',
    content: { media_type: 'image/png' as const, size_bytes: 0, url: '/image' },
  },
};

function setup(): {
  fixture: ComponentFixture<ImageGenerationVisualDemo>;
  ui: () => ImageGenerationUiComponent;
  changeScenario: () => void;
  open: Mock;
  dismiss: Mock;
} {
  const dismiss = vi.fn();
  const open = vi.fn().mockReturnValue({ dismiss });
  TestBed.configureTestingModule({
    imports: [ImageGenerationVisualDemo],
    providers: [provideRouter([]), { provide: MatSnackBar, useValue: { open } }],
  });
  const fixture = TestBed.createComponent(ImageGenerationVisualDemo);
  const host = fixture.nativeElement as HTMLElement;
  fixture.detectChanges();
  const ui = () =>
    fixture.debugElement.query(By.directive(ImageGenerationUiComponent))
      .componentInstance as ImageGenerationUiComponent;
  const changeScenario = () => {
    const button =
      Array.from(host.querySelectorAll('button')).find(
        (item) => item.textContent?.trim() === 'Success' && !item.hasAttribute('aria-current'),
      ) ??
      Array.from(host.querySelectorAll('button')).find(
        (item) => item.textContent?.trim() === 'Connection lost',
      );
    if (!button) throw new Error('Scenario button missing');
    button.click();
    fixture.detectChanges();
  };
  return { fixture, ui, changeScenario, open, dismiss };
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('Image generation visual demo ownership', () => {
  it('clears a real input draft on scenario changes', () => {
    const { fixture, changeScenario } = setup();
    const host = fixture.nativeElement as HTMLElement;
    const textarea = (): HTMLTextAreaElement => {
      const element = host.querySelector('textarea');
      if (!element) throw new Error('Instructions missing');
      return element;
    };
    textarea().value = 'unfinished draft';
    textarea().dispatchEvent(new Event('input'));
    fixture.detectChanges();
    const scenario = Array.from(host.querySelectorAll('button')).find(
      (item) => item.textContent?.trim() === 'Connection lost',
    );
    if (!scenario) throw new Error('Scenario missing');
    scenario.click();
    fixture.detectChanges();
    expect(textarea().value).toBe('');
    expect(scenario.getAttribute('aria-current')).toBeTruthy();
    textarea().value = 'another draft';
    textarea().dispatchEvent(new Event('input'));
    fixture.detectChanges();
    changeScenario();
    expect(textarea().value).toBe('');
    fixture.destroy();
  });

  it('replaces an active run on scenario changes and suppresses its late generation', async () => {
    vi.useFakeTimers();
    const { fixture, ui, changeScenario } = setup();
    const previous = ui();
    const pending = previous.actions().submit('old instructions');
    await vi.advanceTimersByTimeAsync(500);
    await pending;
    fixture.detectChanges();
    expect(previous.state().snapshot?.status).toBe('running');
    changeScenario();
    expect(ui()).not.toBe(previous);
    expect(ui().state().admission).toBe('idle');
    await vi.advanceTimersByTimeAsync(3000);
    fixture.detectChanges();
    expect(ui().state().snapshot).toBeNull();
    fixture.destroy();
  });

  it('ignores content that resolves after its run has been replaced', async () => {
    vi.useFakeTimers();
    let resolveContent: (blob: Blob) => void = () => {
      throw new Error('Missing resolver');
    };
    vi.spyOn(ImageGenerationVisualTransport.prototype, 'content').mockImplementation(
      () =>
        new Promise<Blob>((resolve) => {
          resolveContent = resolve;
        }),
    );
    const createUrl = vi.fn().mockReturnValue('blob:old');
    vi.stubGlobal(
      'URL',
      class extends URL {
        static override createObjectURL = createUrl;
      },
    );
    const { fixture, ui, changeScenario } = setup();
    const pending = ui().actions().submit('draw');
    await vi.advanceTimersByTimeAsync(500);
    await pending;
    await vi.advanceTimersByTimeAsync(2000);
    fixture.detectChanges();
    expect(ui().state().snapshot?.status).toBe('completed');
    changeScenario();
    resolveContent(new Blob(['old'], { type: 'image/png' }));
    await vi.advanceTimersByTimeAsync(0);
    fixture.detectChanges();
    expect(createUrl).not.toHaveBeenCalled();
    expect(ui().state().snapshot).toBeNull();
    fixture.destroy();
    vi.unstubAllGlobals();
  });

  it('cancels pending host feedback and dismisses visible feedback on scenario changes', async () => {
    vi.useFakeTimers();
    const { fixture, ui, changeScenario, open, dismiss } = setup();
    const action = ui().primaryAction();
    if (!action) throw new Error('Primary action missing');
    const pending = action.run(payload);
    const aborted = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    changeScenario();
    await aborted;
    await vi.advanceTimersByTimeAsync(1000);
    expect(open).not.toHaveBeenCalled();
    const next = ui().primaryAction();
    if (!next) throw new Error('Primary action missing');
    const success = next.run(payload);
    await vi.advanceTimersByTimeAsync(1000);
    await success;
    expect(open).toHaveBeenCalledWith('Image received by demo host', undefined, { duration: 3000 });
    changeScenario();
    expect(dismiss).toHaveBeenCalled();
    fixture.destroy();
  });

  it('captures the handoff outcome when an attempt begins', async () => {
    vi.useFakeTimers();
    const { fixture, ui, open } = setup();
    const failureRadio = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      'input[type="radio"][value="failure"]',
    );
    if (!failureRadio) throw new Error('Failure option missing');
    const action = ui().primaryAction();
    if (!action) throw new Error('Primary action missing');
    const pending = action.run(payload);
    failureRadio.click();
    fixture.detectChanges();
    await vi.advanceTimersByTimeAsync(1000);
    await pending;
    expect(open).toHaveBeenCalledOnce();
    const retry = action.run(payload);
    const failure = expect(retry).rejects.toThrow('Demo action failed');
    await vi.advanceTimersByTimeAsync(1000);
    await failure;
    expect(open).toHaveBeenCalledOnce();
    fixture.destroy();
  });
});
