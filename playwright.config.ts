import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: 'http://127.0.0.1:8080',
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'python -m uvicorn src.video_agent.web.app:app --host 127.0.0.1 --port 8080',
    port: 8080,
    reuseExistingServer: true,
    timeout: 15_000,
  },
});
