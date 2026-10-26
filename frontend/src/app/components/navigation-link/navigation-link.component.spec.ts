import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { NavigationLink } from './navigation-link.component';

@Component({
  imports: [NavigationLink],
  template:
    '<a href="/"><app-navigation-link [direction]="direction()">Demos</app-navigation-link></a>',
})
class Host {
  readonly direction = signal<'back' | 'forward'>('forward');
}

describe('NavigationLink', () => {
  it('keeps the label in the enclosing link and puts a decorative arrow on the selected side', () => {
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const link = element.querySelector('a')!;
    expect(link.textContent?.trim()).toMatch(/^Demos\s*→$/);
    expect(link.querySelector('[aria-hidden="true"]')?.textContent?.trim()).toBe('→');
    expect(link.querySelector('a, button')).toBeNull();
    fixture.componentInstance.direction.set('back');
    fixture.detectChanges();
    expect(link.textContent?.trim()).toMatch(/^←\s*Demos$/);
    expect(link.querySelector('[aria-hidden="true"]')?.textContent?.trim()).toBe('←');
  });
});
