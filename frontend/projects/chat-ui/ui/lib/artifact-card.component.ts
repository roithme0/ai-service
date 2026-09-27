import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  computed,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import type { ChatArtifact, ChatArtifactRenderer, JsonValue } from './chat-message';

@Component({
  selector: 'ai-chat-artifact-card',
  imports: [NgTemplateOutlet],
  templateUrl: './artifact-card.component.html',
  styleUrl: './artifact-card.component.scss',
})
export class ArtifactCardComponent implements AfterViewInit, OnDestroy {
  private readonly body = viewChild.required<ElementRef<HTMLElement>>('body');
  private observer: ResizeObserver | null = null;

  readonly artifact = input.required<ChatArtifact>();
  readonly renderer = input<ChatArtifactRenderer | null>(null);
  protected readonly expanded = signal(false);
  protected readonly overflowing = signal(false);
  protected readonly formattedPayload = computed(() => JSON.stringify(this.artifact().payload, null, 2));
  protected readonly renderContext = computed(() => ({
    $implicit: this.artifact().payload,
    artifact: this.artifact(),
  }));

  ngAfterViewInit(): void {
    this.measure();
    if (typeof ResizeObserver !== 'undefined') {
      this.observer = new ResizeObserver(() => this.measure());
      this.observer.observe(this.body().nativeElement);
    }
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }

  private measure(): void {
    if (this.expanded()) {
      return;
    }
    const element = this.body().nativeElement;
    this.overflowing.set(element.scrollHeight > element.clientHeight + 1);
  }
}
