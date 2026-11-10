import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SectionNavComponent } from './section-nav.component';

describe('SectionNavComponent', () => {
  let fixture: ComponentFixture<SectionNavComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SectionNavComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(SectionNavComponent);
    fixture.componentRef.setInput('label', 'Abschnitte');
    fixture.componentRef.setInput('items', [
      { id: 'first', label: 'Erster' },
      { id: 'second', label: 'Zweiter' },
    ]);
    fixture.componentRef.setInput('activeId', 'second');
    fixture.detectChanges();
  });

  it('marks the active item and emits the selected section id', () => {
    const nav = (fixture.nativeElement as HTMLElement).querySelector(
      'nav',
    ) as HTMLElement;
    const buttons = nav.querySelectorAll('button');
    const selected = vi.fn().mockName('selected');
    fixture.componentInstance.selected.subscribe(selected);

    expect(nav.getAttribute('aria-label')).toBe('Abschnitte');
    expect(buttons[0].hasAttribute('aria-current')).toBe(false);
    expect(buttons[1].getAttribute('aria-current')).toBe('location');

    buttons[0].click();
    expect(selected).toHaveBeenCalledTimes(1);
    expect(selected).toHaveBeenCalledWith('first');
  });
});
