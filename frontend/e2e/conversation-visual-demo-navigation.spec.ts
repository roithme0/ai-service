import { test, expect } from '@playwright/test';
import { LandingPage } from './support/landing-page';
import { ConversationVisualDemo } from './support/conversation-visual-demo';

test.describe('Demo navigation', () => {
  test('opens the conversation visual demo and returns to the landing page', async ({ page }) => {
    const landing = new LandingPage(page);
    const demo = new ConversationVisualDemo(page);
    await landing.goto();
    await landing.openConversationVisualDemo();

    await expect(page).toHaveURL((url) => url.pathname === '/demos/conversation/visual');
    await expect(demo.title).toBeVisible();
    await expect(demo.scriptedBadge).toBeVisible();

    await demo.returnToLandingPage();

    await expect(page).toHaveURL((url) => url.pathname === '/');
    await expect(landing.heading).toBeVisible();
    await expect(landing.conversationVisualDemoLink).toBeVisible();
    await expect(landing.conversationLiveDemoLink).toBeVisible();
  });
});
