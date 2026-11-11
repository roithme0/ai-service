import { Component } from '@angular/core';
import { DemoCard } from '../../components/demo-card/demo-card.component';

@Component({
  selector: 'app-demo-landing',
  imports: [DemoCard],
  templateUrl: './demo-landing.component.html',
  styleUrl: './demo-landing.component.scss',
})
export class DemoLanding {}
