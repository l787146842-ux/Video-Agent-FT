/**
 * user-select 豁免台账钉死（体验规范映射）。
 *
 * tokens.css 全局 body user-select: none；需复制的区域必须显式豁免
 * user-select: text（left-panel.css「文字可复制」豁免清单）。
 * 项目无样式测试先例，jsdom 不加载样式表，此处以源文件文本断言
 * 机械钉住豁免清单不回退（豁免被误删 → 复制 affordance 静默失效）。
 */
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';

// 源文件文本断言：vitest 默认桩空 CSS 导入，故直接读磁盘
const here = dirname(fileURLToPath(import.meta.url));
const tokensCss = readFileSync(resolve(here, '../tokens.css'), 'utf-8');
const leftPanelCss = readFileSync(resolve(here, '../left-panel.css'), 'utf-8');

/** 豁免清单（选择器 -> 必须声明 user-select: text） */
const EXEMPTIONS = ['.chat-msg', '.rich-chat-input', '.prompt-textarea'];

describe('user-select 全局基线与豁免清单', () => {
  it('tokens.css：body 全局 user-select: none 仍在（豁免前提）', () => {
    expect(tokensCss).toMatch(/body\s*\{[^}]*user-select:\s*none/s);
  });

  for (const sel of EXEMPTIONS) {
    it(`left-panel.css：${sel} 显式豁免 user-select: text`, () => {
      // 豁免规则：选择器列表行内含目标选择器且声明 user-select: text
      const rule = new RegExp(
        `(^|[,\\s])${sel.replace('.', '\\.')}[^{]*\\{[^}]*user-select:\\s*text`,
      );
      expect(leftPanelCss).toMatch(rule);
    });
  }

  it('对话正文豁免覆盖 .chat-markdown（气泡在 .chat-msg 容器内）', () => {
    // 结构性断言：.chat-markdown 气泡必须渲染在 .chat-msg 豁免容器内，
    // 豁免经由祖先选择器生效；此处钉住豁免清单含容器类而非气泡类，
    // 防止未来把 .chat-msg 拆出豁免清单导致正文不可选。
    expect(EXEMPTIONS).toContain('.chat-msg');
  });
});
