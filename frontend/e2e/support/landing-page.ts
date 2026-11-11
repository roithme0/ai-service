import { type Locator, type Page } from '@playwright/test';

export class LandingPage {
  readonly heading: Locator;
  readonly conversationVisualDemoLink: Locator;
  readonly conversationLiveDemoLink: Locator;

  constructor(private readonly page: Page) {
    this.heading = page.getByRole('heading', { name: 'Choose a demo', exact: true });
    this.conversationVisualDemoLink = page.getByRole('link', {
      name: /^Conversation Visual Demo\b/,
    });
    this.conversationLiveDemoLink = page.getByRole('link', { name: /^Conversation Live Demo\b/ });
  }

  async goto(): Promise<void> {
    await this.page.goto('/');
  }

  async openConversationVisualDemo(): Promise<void> {
    await this.conversationVisualDemoLink.click();
  }

  async openConversationLiveDemo(): Promise<void> {
    await this.conversationLiveDemoLink.click();
  }
}
