import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    browser: {
      screenshotFailures: true,
      screenshotDirectory: 'projects/chat-ui/test-results/screenshots',
      trace: {
        mode: 'retain-on-failure',
        tracesDir: 'projects/chat-ui/test-results/traces',
      },
    },
  },
});
