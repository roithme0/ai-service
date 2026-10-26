import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { DemoTag } from './demo-tag.component';

describe('DemoTag', () => {
  it('updates when the host changes demo type', () => {
    const fixture = TestBed.createComponent(DemoTag);
    fixture.componentRef.setInput('label', 'Scripted');
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent?.trim()).toBe('Scripted');
    fixture.componentRef.setInput('label', 'Live');
    fixture.detectChanges();
    expect(element.textContent?.trim()).toBe('Live');
  });
});
