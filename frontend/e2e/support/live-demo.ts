import { type Locator, type Page } from '@playwright/test';

export class LiveDemo {
  readonly title: Locator;
  readonly liveBadge: Locator;
  readonly landingPageLink: Locator;

  constructor(page: Page) {
    const header = page.getByRole('banner');
    this.title = header.getByText('Live Demo', { exact: true });
    this.liveBadge = header.getByText('Live', { exact: true });
    this.landingPageLink = header
      .getByRole('navigation', { name: 'Demo navigation' })
      .getByRole('link', { name: 'Demos', exact: true });
  }

  async returnToLandingPage(): Promise<void> {
    await this.landingPageLink.click();
  }
}
