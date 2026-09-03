// @ts-check
import tseslint from '@typescript-eslint/eslint-plugin';
import tsparser from '@typescript-eslint/parser';
import solid from 'eslint-plugin-solid';

export default [
  {
    files: ['src/web/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsparser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tseslint,
      solid,
    },
    rules: {
      // 文件行数（架构铁律 10.1：单文件 ≤ 250 行）。
      // 任务 #11 消 Goodhart 化降级：error → warn。理由：硬红线诱发“为凑行数而拆”
      // 的形式主义拆分（4 个顶格文件为证：SkillPicker/LayoutShell/sse-events/
      // sse-connection），行数达标但关注点未收敛。
      // 2026-09-02「治理闸机减负」裁决：check_file_lines 已降为信息工具、
      // 不再挂 acceptance 门禁（无硬闸兜底）；本规则维持 warn 软提醒，
      // 超限处置走人工审查立项（D-02 挂账口径）。
      'max-lines': ['warn', { max: 250, skipBlankLines: true, skipComments: true }],

      // 类型安全
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],

      // 代码质量
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-debugger': 'error',
      'prefer-const': 'error',
      'no-var': 'error',
      'no-redeclare': 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],

      // Solid 响应式规则
      'solid/reactivity': 'warn',
      'solid/no-destructure': 'warn',
      'solid/jsx-no-undef': 'error',
      'solid/self-closing-comp': 'warn',
    },
  },

  // 生成物豁免：api.generated.ts 由 scripts/gen_api_types.py 生成（六轮 S2 路线 a），
  // 行数随后端 schema 自然增长，不适用人工文件的 250 行红线
  {
    files: ['src/web/types/api.generated.ts'],
    rules: {
      'max-lines': 'off',
    },
  },

  // 架构铁律 10.2：组件/stores 不得 import app 入口（禁止循环依赖）
  {
    files: ['src/web/components/**/*.tsx', 'src/web/stores/**/*.ts', 'src/web/lib/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: ['**/app', '**/app.ts', '**/app.tsx'],
      }],
    },
  },

  // 架构铁律 10.1：API 调用集中在 api/，其余层不得直接写 fetch()。
  // 前端批次1 反向枚举：files 覆盖 src/web/** 全部（含 stores/hooks/router 等旧盲区），
  // 仅豁免 api/**（fetch 唯一实现处）。SSE/流式传输封装（reconnecting-sse/generate-polling）
  // 结构性无法走 JSON helper，在各自 fetch 处就地 eslint-disable 并注明理由。
  {
    files: ['src/web/**/*.{ts,tsx}'],
    ignores: ['src/web/api/**'],
    rules: {
      'no-restricted-syntax': ['warn', {
        selector: "CallExpression[callee.name='fetch']",
        message: '架构铁律 10.1：fetch() 应封装在 api/ 层，组件请调用 api/ 导出的函数。',
      }],
    },
  },
];
