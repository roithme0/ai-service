import { test, expect } from '@playwright/test';
import { LandingPage } from './support/landing-page';
import { LiveDemo } from './support/live-demo';

test.describe('Demo navigation', () => {
  test('opens the live demo and returns to the landing page', async ({ page }) => {
    const landing = new LandingPage(page);
    const demo = new LiveDemo(page);
    await landing.goto();
    await landing.openLiveDemo();

    await expect(page).toHaveURL((url) => url.pathname === '/demos/live');
    await expect(demo.title).toBeVisible();
    await expect(demo.liveBadge).toBeVisible();

    await demo.returnToLandingPage();

    await expect(page).toHaveURL((url) => url.pathname === '/');
    await expect(landing.heading).toBeVisible();
    await expect(landing.scriptedDemoLink).toBeVisible();
    await expect(landing.liveDemoLink).toBeVisible();
  });
});
