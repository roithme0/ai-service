import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    browser: {
      screenshotFailures: true,
      screenshotDirectory: 'projects/image-generation/test-results/screenshots',
      trace: {
        mode: 'retain-on-failure',
        tracesDir: 'projects/image-generation/test-results/traces',
      },
    },
  },
});
