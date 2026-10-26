import type { Routes } from '@angular/router';
import { DemoLanding } from './pages/demo-landing/demo-landing.component';

export const routes: Routes = [
  { path: '', pathMatch: 'full', component: DemoLanding },
  {
    path: 'demos/live',
    loadComponent: () =>
      import('./pages/live-demo/live-demo.component').then((page) => page.LiveDemo),
  },
  {
    path: 'demos/visual',
    loadComponent: () =>
      import('./pages/visual-demo/visual-demo.component').then((page) => page.VisualDemo),
  },
];
