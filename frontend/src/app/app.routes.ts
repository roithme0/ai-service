import type { Routes } from '@angular/router';
import { DemoLanding } from './pages/demo-landing/demo-landing.component';
export const routes: Routes = [
  { path: '', pathMatch: 'full', component: DemoLanding },
  {
    path: 'demos/conversation/visual',
    loadComponent: () =>
      import('./pages/conversation-visual-demo/conversation-visual-demo.component').then(
        (page) => page.ConversationVisualDemo,
      ),
  },
  {
    path: 'demos/conversation/live',
    loadComponent: () =>
      import('./pages/conversation-live-demo/conversation-live-demo.component').then(
        (page) => page.ConversationLiveDemo,
      ),
  },
  {
    path: 'demos/image-generation/visual',
    loadComponent: () =>
      import('./pages/image-generation-visual-demo/image-generation-visual-demo.component').then(
        (page) => page.ImageGenerationVisualDemo,
      ),
  },
  {
    path: 'demos/image-generation/live',
    loadComponent: () =>
      import('./pages/image-generation-live-demo/image-generation-live-demo.component').then(
        (page) => page.ImageGenerationLiveDemo,
      ),
  },
];
