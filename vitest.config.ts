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
      // P4-19 回归防护：覆盖率随 vitest 常开收集（含 acceptance 既有 vitest 步骤），
      // 对话核心三模块 + 任务 #10 纳入的四个对话流组件 + 任务 #13 F0 扩围的
      // 六个高风险交互件，80% 行覆盖闸——劣化即红
      //（vitest 4 支持按 glob 键设阈值）
      enabled: true,
      provider: 'v8',
      // F-6：json-summary 供前端覆盖率棘轮（scripts/check_fe_cov_ratchet.py）读取，
      // 产出 coverage/coverage-summary.json；text 保持人读报表不变。
      reporter: ['text', 'json-summary'],
      include: ['src/web/**/*.{ts,tsx}'],
      exclude: ['src/web/**/__tests__/**'],
      thresholds: {
        'src/web/stores/chat.ts': { lines: 80 },
        'src/web/lib/message-affordances.ts': { lines: 80 },
        'src/web/lib/turn-groups.ts': { lines: 80 },
        'src/web/components/right-panel/StreamingBubble.tsx': { lines: 80 },
        'src/web/components/right-panel/StageCard.tsx': { lines: 80 },
        'src/web/components/right-panel/GateWarnings.tsx': { lines: 80 },
        'src/web/components/right-panel/AgentTimeline.tsx': { lines: 80 },
        // F0 扩围（轮次账本卡统一的前置安全绳：先锁定既有行为再动刀）
        'src/web/components/right-panel/ConfirmActions.tsx': { lines: 80 },
        'src/web/components/right-panel/DecisionFormCard.tsx': { lines: 80 },
        'src/web/components/right-panel/ChatFeed.tsx': { lines: 80 },
        'src/web/components/right-panel/ChatMessageItem.tsx': { lines: 80 },
        'src/web/components/right-panel/QueuedMessagesBar.tsx': { lines: 80 },
        'src/web/components/right-panel/StageProgressBar.tsx': { lines: 80 },
        // F2 阶段二：轮次账本卡（双相位渲染统一壳）纳入阈值闸
        'src/web/components/right-panel/TurnLedgerCard.tsx': { lines: 80 },
      },
    },
  },
});
