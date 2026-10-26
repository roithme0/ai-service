import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';
import { DemoHeader } from './demo-header.component';

describe('DemoHeader', () => {
  it.each([
    { label: 'Visual Demo', tag: 'Scripted' },
    { label: 'Live Demo', tag: 'Live' },
  ])('identifies $label and links back to the selector', ({ label, tag }) => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(DemoHeader);
    fixture.componentRef.setInput('label', label);
    fixture.componentRef.setInput('tag', tag);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelector('.demo-label')?.textContent).toBe(label);
    expect(element.querySelector('app-demo-tag')?.textContent?.trim()).toBe(tag);
    const link = element.querySelector('nav a')!;
    expect(link.getAttribute('href')).toBe('/');
    expect(link.textContent).toContain('Demos');
  });
});
