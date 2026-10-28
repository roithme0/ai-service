import { test, expect } from '@playwright/test';
import { LandingPage } from './support/landing-page';
import { ScriptedDemo } from './support/scripted-demo';

test.describe('Demo navigation', () => {
  test('opens the visual demo and returns to the landing page', async ({ page }) => {
    const landing = new LandingPage(page);
    const demo = new ScriptedDemo(page);
    await landing.goto();
    await landing.openScriptedDemo();

    await expect(page).toHaveURL((url) => url.pathname === '/demos/visual');
    await expect(demo.title).toBeVisible();
    await expect(demo.scriptedBadge).toBeVisible();

    await demo.returnToLandingPage();

    await expect(page).toHaveURL((url) => url.pathname === '/');
    await expect(landing.heading).toBeVisible();
    await expect(landing.scriptedDemoLink).toBeVisible();
    await expect(landing.liveDemoLink).toBeVisible();
  });
});
