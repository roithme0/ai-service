import { test, expect } from '@playwright/test';

test.describe('Demo navigation', () => {
  test('opens the live demo and returns to the landing page', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /^Live Demo\b/ }).click();

    await expect(page).toHaveURL((url) => url.pathname === '/demos/live');
    const header = page.getByRole('banner');
    await expect(header.getByText('Live Demo', { exact: true })).toBeVisible();
    await expect(header.getByText('Live', { exact: true })).toBeVisible();

    await header
      .getByRole('navigation', { name: 'Demo navigation' })
      .getByRole('link', { name: 'Demos', exact: true })
      .click();

    await expect(page).toHaveURL((url) => url.pathname === '/');
    await expect(page.getByRole('heading', { name: 'Choose a demo', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /^Visual Demo\b/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /^Live Demo\b/ })).toBeVisible();
  });
});
