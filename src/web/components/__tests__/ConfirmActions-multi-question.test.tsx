/**
 * 暂停卡多问题结构（2026-09-21 批F，事故 4444/Q2③+Q3）。
 *
 * 背景（4444 实跑取证）：模型有 5 个维度要问（画幅/时长/风格/角色造型/
 * 二向箔显名），手上却只有**一个扁平 options + 一个 multi_select**，只能自创
 * "套餐"把前四维压成互斥预设、把第五维塞进 detail；为「怎么问这一个问题」
 * 花了 8 段思考/2740 字/34.3s，且第五维**结构上无法被用户回答** → 模型自判
 * 「未回复即遵循原文」并把它写成了既定规格。
 * 对齐 dsh `ask_user_question` 的 `questions[]`：一次可问 N 个问题。
 *
 * 钉死契约：
 * ① pauseQuestions 非空 → 逐问一块（各带自己的 header/问句/detail/选项）；
 * ② 标了 multi_select 的问题渲染复选框，可勾多个；发送时**各占一行**；
 * ③ 底部单一发送按钮，各问所选**按问题顺序**逐行拼接（与既有向导同口径）；
 * ④ 未答完不可发送（防半截答复）；无选项的问题给自定义输入兜底提示；
 * ⑤ pauseQuestions 空/缺省 → **逐字走原单问/向导分支**（旧消息零变化）。
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

beforeEach(() => {
  sendMock.mockClear();
});

describe('批F：多问题卡（一次问 N 个问题）', () => {
  it('① 逐问一块：每问自带问句，块数 = 问题数', () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '画幅选哪个？' }),
        q({ id: 'b', question: '二向箔是否显名？', options: [{ label: '显名' }, { label: '不显名' }] }),
      ])} />
    ));
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    expect(blocks).toHaveLength(2);
    expect(blocks[0].textContent).toContain('画幅选哪个？');
    expect(blocks[1].textContent).toContain('二向箔是否显名？');
  });

  it('② 每问的 header/detail 各归各块，detail 不变成选项', () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ header: '规格', detail: '决定后续所有镜头的基调。' }),
        q({ id: 'b', question: '第二问？', header: '显名', detail: '台词里是否直呼其名。' }),
      ])} />
    ));
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    expect(blocks[0].querySelector('.confirm-wizard-header')?.textContent).toBe('规格');
    expect(blocks[0].querySelector('.confirm-wizard-detail')?.textContent)
      .toBe('决定后续所有镜头的基调。');
    expect(blocks[1].querySelector('.confirm-wizard-header')?.textContent).toBe('显名');
    // detail 不进选项区
    const labels = Array.from(container.querySelectorAll('.confirm-option-label'))
      .map((el) => el.textContent);
    expect(labels).not.toContain('决定后续所有镜头的基调。');
  });

  it('③ 多选问题渲染复选框，可勾多个（单选问题仍单选）', () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '单选问？' }),
        q({ id: 'b', question: '多选问？', multi_select: true }),
      ])} />
    ));
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    // 多选块的卡片带 .multi 容器 + checkbox 形状
    expect(blocks[0].querySelector('.confirm-options.multi')).toBeNull();
    expect(blocks[1].querySelector('.confirm-options.multi')).not.toBeNull();
    expect(blocks[1].querySelectorAll('.confirm-option-radio.checkbox')).toHaveLength(2);
  });

  it('③b 多选可同时勾选多项；单选切换则互斥', () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '单选问？' }),
        q({ id: 'b', question: '多选问？', multi_select: true }),
      ])} />
    ));
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    const single = blocks[0].querySelectorAll('.confirm-option-card');
    fireEvent.click(single[0]);
    fireEvent.click(single[1]);
    // 单选：只有第二个选中
    expect(blocks[0].querySelectorAll('.confirm-option-card.selected')).toHaveLength(1);
    const multi = blocks[1].querySelectorAll('.confirm-option-card');
    fireEvent.click(multi[0]);
    fireEvent.click(multi[1]);
    // 多选：两个都选中
    expect(blocks[1].querySelectorAll('.confirm-option-card.selected')).toHaveLength(2);
  });

  it('④ 未答完不可发送；答完后各问所选按问题顺序逐行发送', async () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '第一问？', options: [{ label: '画幅16:9' }] }),
        q({ id: 'b', question: '第二问？', options: [{ label: '不显名' }] }),
      ])} />
    ));
    const btn = container.querySelector('.confirm-btn.primary') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);           // 未答完
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    fireEvent.click(blocks[0].querySelector('.confirm-option-card')!);
    expect(btn.disabled).toBe(true);           // 只答一问仍不可发
    fireEvent.click(blocks[1].querySelector('.confirm-option-card')!);
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(sendMock).toHaveBeenCalledTimes(1);
    // 顺序 = 问题顺序，逐行拼接
    expect(sendMock.mock.calls[0][0]).toBe('画幅16:9\n不显名');
  });

  it('④b 多选题内多个选中项同样各占一行', async () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '多选问？', multi_select: true,
            options: [{ label: '冷调' }, { label: '暖调' }] }),
      ])} />
    ));
    const cards = container.querySelectorAll('.confirm-option-card');
    fireEvent.click(cards[0]);
    fireEvent.click(cards[1]);
    fireEvent.click(container.querySelector('.confirm-btn.primary')!);
    expect(sendMock.mock.calls[0][0]).toBe('冷调\n暖调');
  });

  it('⑥ 发送另携问题级 answers[]（批J，对齐 dsh AskUserQuestionAnswerItem）', async () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'ratio', question: '画幅？', options: [{ label: '16:9' }] }),
        q({ id: 'naming', question: '显名？', options: [{ label: '不显名' }] }),
      ])} />
    ));
    const blocks = container.querySelectorAll('[data-testid="pause-question-block"]');
    fireEvent.click(blocks[0].querySelector('.confirm-option-card')!);
    fireEvent.click(blocks[1].querySelector('.confirm-option-card')!);
    fireEvent.click(container.querySelector('.confirm-btn.primary')!);
    // 第 2 参与 = pauseResponse；结构化面按问题 id 逐项对应
    const opts = sendMock.mock.calls[0][1] as {
      pauseResponse?: { value: string; answers?: Array<{ id: string; selected: string[] }> };
    };
    expect(opts.pauseResponse?.value).toBe('16:9\n不显名');   // 扁平面照旧
    expect(opts.pauseResponse?.answers).toEqual([
      { id: 'ratio', selected: ['16:9'] },
      { id: 'naming', selected: ['不显名'] },
    ]);
  });

  it('⑥b 多选题的 answers.selected 含全部勾选项（不逐行拆）', async () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'tone', question: '基调？', multi_select: true,
            options: [{ label: '冷调' }, { label: '暖调' }] }),
      ])} />
    ));
    const cards = container.querySelectorAll('.confirm-option-card');
    fireEvent.click(cards[0]);
    fireEvent.click(cards[1]);
    fireEvent.click(container.querySelector('.confirm-btn.primary')!);
    const opts = sendMock.mock.calls[0][1] as {
      pauseResponse?: { answers?: Array<{ id: string; selected: string[] }> };
    };
    expect(opts.pauseResponse?.answers).toEqual([
      { id: 'tone', selected: ['冷调', '暖调'] },
    ]);
  });

  it('⑥c 旧单问分支不携 answers（旧路径零变化）', async () => {
    const { container } = render(() => (
      <ConfirmActions message={{
        sender: 'agent', text: '', confirm: '旧问句？', pauseId: 'old',
        confirmOptions: [{ label: '旧选项A' }],
      }} />
    ));
    fireEvent.click(container.querySelector('.confirm-option-card')!);
    fireEvent.click(container.querySelector('.confirm-btn.primary')!);
    const opts = sendMock.mock.calls[0][1] as { pauseResponse?: Record<string, unknown> };
    expect(opts.pauseResponse).toBeTruthy();
    expect('answers' in (opts.pauseResponse || {})).toBe(false);
  });

  it('④c 无选项的问题给自定义输入兜底提示（不是死路）', () => {
    const { container } = render(() => (
      <ConfirmActions message={msgWith([
        q({ id: 'a', question: '开放问？', options: [] }),
      ])} />
    ));
    const block = container.querySelector('[data-testid="pause-question-block"]')!;
    expect(block.querySelector('.confirm-question-hint')).not.toBeNull();
  });

  it('⑤ pauseQuestions 空/缺省 → 逐字走原单问分支（旧消息零变化）', () => {
    const { container } = render(() => (
      <ConfirmActions message={{
        sender: 'agent', text: '', confirm: '旧问句？', pauseId: 'old',
        pauseHeader: '旧标题', pauseDetail: '旧说明',
        confirmOptions: [{ label: '旧选项A' }],
      }} />
    ));
    // 无多问题块
    expect(container.querySelector('[data-testid="pause-question-block"]')).toBeNull();
    // 原单问分支照旧：题面 + header + detail
    expect(container.querySelector('.confirm-wizard-question')?.textContent).toBe('旧问句？');
    expect(container.querySelector('.confirm-wizard-header')?.textContent).toBe('旧标题');
    expect(container.querySelector('.confirm-wizard-detail')?.textContent).toBe('旧说明');
    expect(container.querySelectorAll('.confirm-option-label')).toHaveLength(1);
  });

  it('⑤b 空数组同样回落原分支（非空才走多问）', () => {
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
