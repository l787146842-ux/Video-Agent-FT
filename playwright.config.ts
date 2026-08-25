import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  // 偶发抖动（webServer 冷启动/网络帧时序）给一次重试；trace 仅在重试时留存，
  // 避免全量 trace 占满磁盘（任务 #6 e2e 保障扩围）
  retries: 1,
  use: {
    baseURL: 'http://127.0.0.1:8080',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'python -m uvicorn src.video_agent.web.app:app --host 127.0.0.1 --port 8080',
    port: 8080,
    reuseExistingServer: true,
    timeout: 15_000,
  },
});
