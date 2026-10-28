import { type Locator, type Page } from '@playwright/test';

export class LandingPage {
  readonly heading: Locator;
  readonly scriptedDemoLink: Locator;
  readonly liveDemoLink: Locator;

  constructor(private readonly page: Page) {
    this.heading = page.getByRole('heading', { name: 'Choose a demo', exact: true });
    this.scriptedDemoLink = page.getByRole('link', { name: /^Visual Demo\b/ });
    this.liveDemoLink = page.getByRole('link', { name: /^Live Demo\b/ });
  }

  async goto(): Promise<void> {
    await this.page.goto('/');
  }

  async openScriptedDemo(): Promise<void> {
    await this.scriptedDemoLink.click();
  }

  async openLiveDemo(): Promise<void> {
    await this.liveDemoLink.click();
  }
}
