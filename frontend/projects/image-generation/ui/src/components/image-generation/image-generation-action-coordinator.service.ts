import { Injectable, OnDestroy, signal } from '@angular/core';

@Injectable()
export class ImageGenerationActionCoordinator implements OnDestroy {
  private readonly pendingState = signal(false);
  readonly pending = this.pendingState.asReadonly();
  private actionEpoch = 0;
  private resultEpoch = 0;
  private destroyed = false;
  private submission: string | null = null;

  get submittingInstructions(): string | null {
    return this.submission;
  }

  clearResult(preserveAction: boolean): void {
    this.resultEpoch++;
    if (!preserveAction) {
      this.actionEpoch++;
      this.submission = null;
      this.pendingState.set(false);
    }
  }

  invoke(
    action: () => void | Promise<void>,
    onError: () => void,
    submission?: string,
  ): Promise<void> {
    return this.run(action, onError, 'action', submission);
  }

  handoff(action: () => Promise<void>, onError: () => void): Promise<void> {
    return this.run(action, onError, 'result');
  }

  private async run(
    action: () => void | Promise<void>,
    onError: () => void,
    lifetime: 'action' | 'result',
    submission?: string,
  ): Promise<void> {
    if (this.pending() || this.destroyed) return;
    this.pendingState.set(true);
    if (submission !== undefined) this.submission = submission;
    const epoch = lifetime === 'result' ? this.resultEpoch : this.actionEpoch;
    const isCurrent = (): boolean =>
      !this.destroyed && epoch === (lifetime === 'result' ? this.resultEpoch : this.actionEpoch);
    try {
      await action();
    } catch {
      if (isCurrent()) onError();
    } finally {
      if (isCurrent()) {
        if (submission !== undefined) this.submission = null;
        this.pendingState.set(false);
      }
    }
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    this.clearResult(false);
  }
}
