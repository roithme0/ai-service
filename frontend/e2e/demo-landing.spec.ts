import { test, expect } from '@playwright/test';

test('shows links to both demos', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('link', { name: /^Visual Demo\b/ })).toBeVisible();
  await expect(page.getByRole('link', { name: /^Live Demo\b/ })).toBeVisible();
});
