import { test, expect } from '@playwright/test';
import { LandingPage } from './support/landing-page';
import { ConversationLiveDemo } from './support/conversation-live-demo';

test.describe('Demo navigation', () => {
  test('opens the conversation live demo and returns to the landing page', async ({ page }) => {
    const landing = new LandingPage(page);
    const demo = new ConversationLiveDemo(page);
    await landing.goto();
    await landing.openConversationLiveDemo();

    await expect(page).toHaveURL((url) => url.pathname === '/demos/conversation/live');
    await expect(demo.title).toBeVisible();
    await expect(demo.liveBadge).toBeVisible();

    await demo.returnToLandingPage();

    await expect(page).toHaveURL((url) => url.pathname === '/');
    await expect(landing.heading).toBeVisible();
    await expect(landing.conversationVisualDemoLink).toBeVisible();
    await expect(landing.conversationLiveDemoLink).toBeVisible();
  });
});
