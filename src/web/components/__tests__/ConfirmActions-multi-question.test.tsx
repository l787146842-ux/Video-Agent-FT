/**
 * 暂停卡多问题**分页作答**（2026-09-21 A 批，对齐 dsh
 * `packages/client/ui-user-questions/src/client/QuestionComposer.tsx::QuestionFlow`）。
 *
 * 历史：批F 原契约 = 「逐问一块 + 底部单一发送」（一次全列）；A 批按用户
 * 裁决「按 dsh 去做，直接抄」改为分页，本文件契约随之改写。
 *
 * 钉死契约：
 * ① 一页一题（同一时刻只渲染一个问题块）；pager 指示「i / N」；
 * ② 单选点选自动翻页（非末题）；多选不自动翻页；
 * ③ 草稿随页保留（翻回已答页选中仍在）；
 * ④ 「跳过」显式登记（末题跳过即发送；跳过的题记空答案）；
 * ⑤ 发送时整组校验：缺项跳回缺题并提示；
 * ⑥ 发送 = 逐行文本（旧消费链）+ 问题级 answers（批J 结构化）；
 * ⑦ pauseQuestions 空/缺省 → 逐字走原单问/向导分支（旧消息零变化）。
 */
/// <reference types="node" />
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ConfirmActions } from '../right-panel/ConfirmActions';
import type { ChatMessage, PauseQuestion } from '@/types';

const sendMock = vi.fn((..._args: unknown[]) => Promise.resolve(true));
vi.mock('@/lib/agent-actions', () => ({
  sendUserMessage: (text: string, opts?: unknown) => sendMock(text, opts),
}));
vi.mock('@/lib/providers', () => ({
  apiProvidersFor: () => [{ id: 'volc', name: '火山引擎' }],
  providerModels: () => ['doubao-seed'],
}));

function q(extra: Partial<PauseQuestion> = {}): PauseQuestion {
  return { id: 'q1', question: '第一问？', options: [{ label: 'A' }, { label: 'B' }], ...extra };
}

function msgWith(questions: PauseQuestion[]): ChatMessage {
  return {
    sender: 'agent',
    text: '',
    confirm: '总题面',
    pauseId: 'pause_multi',
    pauseQuestions: questions,
  };
}

/** 渲染并返回常用查询器（分页后同一时刻只有一块） */
function renderFlow(questions: PauseQuestion[]) {
  const { container } = render(() => (<ConfirmActions message={msgWith(questions)} />));
  const block = () => container.querySelector('[data-testid="pause-question-block"]');
  const cards = () => Array.from(container.querySelectorAll('.confirm-option-card'));
  const indicator = () => container.querySelector('.confirm-wizard-indicator')?.textContent || '';
  const byId = (id: string) => container.querySelector(`[data-testid="${id}"]`) as HTMLButtonElement;
  return { container, block, cards, indicator, byId };
}

const TWO_Q: PauseQuestion[] = [
  q({ id: 'a', question: '第一问？', options: [{ label: '画幅16:9' }] }),
  q({ id: 'b', question: '第二问？', options: [{ label: '不显名' }] }),
];

beforeEach(() => {
  sendMock.mockClear();
});

describe('A 批：多问题分页作答（对齐 dsh QuestionFlow）', () => {
  it('① 一页一题：初始只渲染第 1 问，pager 显示 1 / 2', () => {
    const f = renderFlow(TWO_Q);
    expect(f.container.querySelectorAll('[data-testid="pause-question-block"]')).toHaveLength(1);
    expect(f.block()?.textContent).toContain('第一问？');
    expect(f.block()?.textContent).not.toContain('第二问？');
    expect(f.indicator()).toBe('1 / 2');
  });

  it('② 单选点选自动翻页（非末题）；末题点选留在末页', () => {
    const f = renderFlow(TWO_Q);
    fireEvent.click(f.cards()[0]);
    expect(f.indicator()).toBe('2 / 2');
    expect(f.block()?.textContent).toContain('第二问？');
    fireEvent.click(f.cards()[0]);
    expect(f.indicator()).toBe('2 / 2');
  });

  it('③ 草稿随页保留：翻回第 1 题，选中仍在', () => {
    const f = renderFlow(TWO_Q);
    fireEvent.click(f.cards()[0]);                       // 答第 1 题 → 自动到第 2 题
    fireEvent.click(f.byId('pause-flow-prev'));
    expect(f.indicator()).toBe('1 / 2');
    expect(f.container.querySelectorAll('.confirm-option-card.selected')).toHaveLength(1);
  });

  it('④ 多选渲染为复选框，可勾多个且不自动翻页', () => {
    const f = renderFlow([
      q({ id: 'a', multi_select: true, options: [{ label: '冷调' }, { label: '暖调' }] }),
      q({ id: 'b', question: '第二问？' }),
    ]);
    expect(f.container.querySelector('.confirm-options.multi')).not.toBeNull();
    expect(f.container.querySelectorAll('.confirm-option-radio.checkbox')).toHaveLength(2);
    fireEvent.click(f.cards()[0]);
    fireEvent.click(f.cards()[1]);
    expect(f.container.querySelectorAll('.confirm-option-card.selected')).toHaveLength(2);
    expect(f.indicator()).toBe('1 / 2');                 // 多选不翻页
  });

  it('⑤ 跳过：末题跳过即发送（跳过的题记空答案）', () => {
    const f = renderFlow(TWO_Q);
    fireEvent.click(f.cards()[0]);                       // 答第 1 题 → 第 2 题
    fireEvent.click(f.byId('pause-flow-skip'));
    expect(sendMock).toHaveBeenCalledTimes(1);
    expect(sendMock.mock.calls[0][0]).toBe('画幅16:9');
    const opts = sendMock.mock.calls[0][1] as {
      pauseResponse?: { answers?: Array<{ id: string; selected: string[] }> };
    };
    expect(opts.pauseResponse?.answers).toEqual([
      { id: 'a', selected: ['画幅16:9'] },
      { id: 'b', selected: [] },
    ]);
  });

  it('⑥ 整组校验：缺项点发送 → 跳回缺题并提示（不发送）', () => {
    const f = renderFlow(TWO_Q);
    fireEvent.click(f.byId('pause-flow-next'));          // 不答第 1 题，翻到第 2 题
    fireEvent.click(f.cards()[0]);                       // 答第 2 题（末题，不翻）
    fireEvent.click(f.byId('pause-flow-submit'));        // 发送 → 缺第 1 题
    expect(f.indicator()).toBe('1 / 2');
    expect(f.container.querySelector('.confirm-flow-error')?.textContent)
      .toBe('还有问题未作答，已跳回该题');
    expect(sendMock).not.toHaveBeenCalled();
  });

  it('⑦ 发送：逐行文本 + 结构化 answers（第 1 题自定义，第 2 题选项）', () => {
    const f = renderFlow([
      q({ id: 'a', question: '第一问？', options: [] }),  // 无选项 → 自定义兜底
      q({ id: 'b', question: '第二问？', options: [{ label: '不显名' }] }),
    ]);
    fireEvent.click(f.block()!.querySelector('.confirm-btn.secondary')!);
    const ta = f.block()!.querySelector<HTMLTextAreaElement>('.confirm-custom-input')!;
    fireEvent.input(ta, { target: { value: '我自己定 4:3' } });
    fireEvent.click(f.byId('pause-flow-submit'));        // 下一题
    expect(f.indicator()).toBe('2 / 2');
    fireEvent.click(f.cards()[0]);
    fireEvent.click(f.byId('pause-flow-submit'));        // 发送
    expect(sendMock.mock.calls[0][0]).toBe('我自己定 4:3\n不显名');
    const opts = sendMock.mock.calls[0][1] as {
      pauseResponse?: { answers?: unknown };
    };
    expect(opts.pauseResponse?.answers).toEqual([
      { id: 'a', selected: [], custom: '我自己定 4:3' },
      { id: 'b', selected: ['不显名'] },
    ]);
  });

  it('⑧ 当前题未答时主按钮禁用（跳过/翻页仍可用）', () => {
    const f = renderFlow(TWO_Q);
    expect(f.byId('pause-flow-submit').disabled).toBe(true);
    fireEvent.click(f.byId('pause-flow-skip'));
    expect(f.indicator()).toBe('2 / 2');
    expect(f.byId('pause-flow-submit').disabled).toBe(true);
  });

  it('⑨ 各问 header/detail 随页呈现；detail 不变成选项', () => {
    const f = renderFlow([
      q({ id: 'a', header: '规格', detail: '决定后续所有镜头的基调。' }),
      q({ id: 'b', question: '第二问？', header: '显名' }),
    ]);
    expect(f.block()!.querySelector('.confirm-wizard-header')?.textContent).toBe('规格');
    expect(f.block()!.querySelector('.confirm-wizard-detail')?.textContent)
      .toBe('决定后续所有镜头的基调。');
    const labels = Array.from(f.container.querySelectorAll('.confirm-option-label'))
      .map((el) => el.textContent);
    expect(labels).not.toContain('决定后续所有镜头的基调。');
    fireEvent.click(f.byId('pause-flow-next'));
    expect(f.block()!.querySelector('.confirm-wizard-header')?.textContent).toBe('显名');
  });

  it('⑩ 无选项的问题给自定义输入兜底提示（不是死路）', () => {
    const f = renderFlow([q({ id: 'a', question: '开放问？', options: [] })]);
    expect(f.block()!.querySelector('.confirm-question-hint')).not.toBeNull();
  });

  it('⑪ pauseQuestions 空/缺省 → 逐字走原单问分支（旧消息零变化）', () => {
    const { container } = render(() => (
      <ConfirmActions message={{
        sender: 'agent', text: '', confirm: '旧问句？', pauseId: 'old',
        pauseHeader: '旧标题', pauseDetail: '旧说明',
        confirmOptions: [{ label: '旧选项A' }],
      }} />
    ));
    expect(container.querySelector('[data-testid="pause-question-block"]')).toBeNull();
    expect(container.querySelector('.confirm-wizard-question')?.textContent).toBe('旧问句？');
    expect(container.querySelector('.confirm-wizard-header')?.textContent).toBe('旧标题');
    expect(container.querySelector('.confirm-wizard-detail')?.textContent).toBe('旧说明');
    expect(container.querySelectorAll('.confirm-option-label')).toHaveLength(1);
  });

  it('⑫ 空数组同样回落原分支（非空才走多问分页）', () => {
    const { container } = render(() => (
      <ConfirmActions message={{
        sender: 'agent', text: '', confirm: '旧问句？', pauseQuestions: [],
        confirmOptions: [{ label: '旧选项A' }],
      }} />
    ));
    expect(container.querySelector('[data-testid="pause-question-block"]')).toBeNull();
    expect(container.querySelector('.confirm-wizard-question')?.textContent).toBe('旧问句？');
  });
});
