/**
 * ConfirmActions 批次C 三段式问卷卡测试（自 ConfirmActions.test.tsx 按
 * 前端行数红线拆分）。
 *
 * 钉死契约：
 * ① 单组暂停卡三段式：题面（msg.confirm）独立成行 → 选项区紧随 →
 *    自定义输入兜底（DOM 顺序钉死）；
 * ② 多组向导：总题面独立成行 + 页内子题面（组标题）紧随；
 * ③ 总题面与页内子题面同句时不双显（只留一行）；
 * ④ 亮橙问卷卡高亮态禁发光（CSS 文本钉死 box-shadow/text-shadow none）。
 */
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from '@solidjs/testing-library';
import { describe, it, expect, vi } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import type { ChatMessage } from '@/types';

// 与主测试文件同桩：发送/供应商源不入真实链路
vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: () => Promise.resolve(true),
}));
vi.mock('@/lib/providers', () => ({
  apiProvidersFor: () => [{ id: 'volc', name: '火山引擎' }],
  providerModels: () => ['doubao-seed'],
}));

function pauseMessage(options: Array<{ label: string; value?: string; group?: string }> = []): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '「剧本分析」已完成，是否进入下一阶段？',
    pauseId: 'pause_001',
    confirmOptions: options,
  };
}

describe('批次C：暂停卡三段式问卷卡', () => {
  it('单组暂停卡：题面独立成行 → 选项区紧随 → 自定义输入兜底（DOM 顺序钉死）', () => {
    const msg = pauseMessage([
      { label: '方案一', value: 'v1' },
      { label: '方案二', value: 'v2' },
    ]);
    const { container } = render(() => <ConfirmActions message={msg} />);
    const wizard = container.querySelector('.confirm-wizard');
    expect(wizard).toBeTruthy();
    // ① 题面独立成行，文案 = msg.confirm
    expect(container.querySelector('.confirm-wizard-question')?.textContent)
      .toBe('「剧本分析」已完成，是否进入下一阶段？');
    // 三段顺序：题面 → 选项区 → 自定义兜底按钮（其后为 footer）
    const top = Array.from(wizard!.children).slice(0, 3).map((el) => el.classList[0]);
    expect(top).toEqual(['confirm-wizard-question', 'confirm-options', 'confirm-btn']);
  });

  it('多组向导：总题面独立成行 + 页内子题面（组标题）紧随', () => {
    const msg = pauseMessage([
      { label: '写实风', value: 'style_real', group: '画风' },
      { label: '16:9 横屏', value: 'ratio_169', group: '画幅' },
    ]);
    const { container } = render(() => <ConfirmActions message={msg} />);
    const questions = container.querySelectorAll('.confirm-wizard-question');
    expect(questions.length).toBe(2);
    expect(questions[0].textContent).toBe('「剧本分析」已完成，是否进入下一阶段？');
    expect(questions[1].textContent).toBe('画风');
  });

  it('总题面与页内子题面同句时不双显（只留一行）', () => {
    const msg = pauseMessage([{ label: '写实风', value: 'style_real', group: '画风' }]);
    msg.confirm = '画风';
    const { container } = render(() => <ConfirmActions message={msg} />);
    const questions = container.querySelectorAll('.confirm-wizard-question');
    expect(questions.length).toBe(1);
    expect(questions[0].textContent).toBe('画风');
  });

  // CSS 侧钉死（vitest 桩空 CSS 导入，源文件文本断言同 user-select 先例）
  const here = dirname(fileURLToPath(import.meta.url));
  const chatCardsCss = readFileSync(resolve(here, '../../styles/chat-cards.css'), 'utf-8');

  it('chat-cards.css：亮橙问卷卡高亮态禁发光（box-shadow/text-shadow 钉死 none）', () => {
    // 禁发光规则覆盖问卷卡容器/选项卡悬停与选中态/主按钮
    expect(chatCardsCss).toMatch(
      /\.confirm-wizard[^{]*\.confirm-option-card[^{]*\{[^}]*box-shadow:\s*none;\s*text-shadow:\s*none/s,
    );
  });
});
