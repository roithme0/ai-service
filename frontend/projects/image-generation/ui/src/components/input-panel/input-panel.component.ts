import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { Component, ElementRef, input, output, viewChild } from '@angular/core';

let nextId = 0;

@Component({
  selector: 'ai-image-generation-input-panel',
  standalone: true,
  imports: [MatButtonModule, MatFormFieldModule, MatInputModule],
  templateUrl: './input-panel.component.html',
  styleUrls: ['../panel.scss', './input-panel.component.scss'],
})
export class ImageGenerationInputPanelComponent {
  readonly draft = input.required<string>();
  readonly error = input<string | null>(null);
  readonly pending = input(false);
  readonly canGoBack = input(false);
  readonly draftChange = output<string>();
  readonly generate = output<void>();
  readonly back = output<void>();
  readonly inputId = `image-instructions-${++nextId}`;
  readonly errorId = `${this.inputId}-error`;
  private readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  private readonly textarea = viewChild<ElementRef<HTMLTextAreaElement>>('textarea');

  focusHeading(): void {
    this.heading()?.nativeElement.focus();
  }

  focusInstructions(): void {
    this.textarea()?.nativeElement.focus();
  }
}
