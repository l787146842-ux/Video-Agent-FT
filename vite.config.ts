import { defineConfig } from 'vite';
import solidPlugin from 'vite-plugin-solid';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// 后端端口：config.py 默认 8080，可通过环境变量覆盖
const API_PORT = process.env.VITE_API_PORT || '8080';
const API_TARGET = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  // B3/F25：Tailwind 已摘除（组件实际使用手写语义 CSS + tokens.css，
  // 工具类使用率 ~0，纯构建开销），样式系统唯一化为 styles/*.css
  plugins: [
    solidPlugin(),
  ],
  define: {
    // 构建时间戳：排查"浏览器跑的是不是最新构建"时一眼可查（控制台/BUILD_ID）
    __BUILD_ID__: JSON.stringify(new Date().toISOString()),
  },
  // root 设为 src/web：让 HTML 入口输出到 dist 根目录（而非 dist/src/web/）
  root: resolve(__dirname, 'src/web'),
  // 所有构建产物 URL 加 /static/dist/ 前缀（后端 mount 在此路径）
  base: '/static/dist/',
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src/web'),
    },
  },
  // Vite dev server 默认 5174（5173 被占用时自动递增）
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        // SSE 关键：禁用代理超时，保证长连接不断
        timeout: 0,
        proxyTimeout: 0,
      },
      '/static': {
        target: API_TARGET,
        changeOrigin: true,
        // /static/dist/ 由 Vite 自己服务（base 路径），不转发后端
        bypass: (req) => {
          if (req.url?.startsWith('/static/dist')) return req.url;
        },
      },
      '/workspace': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    // outDir 相对 root 解析；用绝对路径避免歧义
    outDir: resolve(__dirname, 'static/dist'),
    emptyOutDir: true,
    rollupOptions: {
      // 入口：src/web/index.html（root 下的 index.html）
      input: resolve(__dirname, 'src/web/index.html'),
      output: {
        // 带 hash 文件名，配合长期缓存
        entryFileNames: 'studio-[hash].js',
        chunkFileNames: '[name]-[hash].js',
        assetFileNames: '[name]-[hash].[ext]',
      },
    },
  },
});
