import { defineConfig } from 'vitest/config';
import solidPlugin from 'vite-plugin-solid';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  // hot:false — 测试环境禁用 solid-refresh HMR 注入（否则 .tsx 组件测试加载报 file:///@solid-refresh 解析错误）
  plugins: [solidPlugin({ hot: false })],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src/web'),
    },
    conditions: ['development', 'browser'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/web/**/__tests__/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/web/**/*.{ts,tsx}'],
      exclude: ['src/web/**/__tests__/**'],
    },
  },
});
