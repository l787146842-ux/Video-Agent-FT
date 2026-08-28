/**
 * 任务 #8 机械断言（前端体验规范 §二 故事板微调框 / 台账 #9）：
 * 「仅悬停草稿卡片 300ms 后缓缓浮现」的时序分支断言（JS 侧挂表延迟）。
 *
 * ① 悬停草稿卡即刻不弹（禁止瞬时弹出）；
 * ② 悬停满 300ms 浮现（299ms 仍不弹、300ms 弹出，双夹逼锁死阈值）；
 * ③ 300ms 内移出分组 → 挂表取消，永不浮现（扫过列表不反复弹出）;
 * ④ 悬停标题/描述等非卡片区域不挂表、不弹出（仅悬停草稿卡触发）；
 * ⑤ 展开后输入意见点「微调」能发出（浮现不是摆设）。
 *
 * 本文件断言对象是 GroupCard 挂表时序与 GroupAdjustBox 显隐，与条款无关的
 * 重组件（DraftCard/描述编辑器/发送通道）以桩替代，控制测试面。
 * CSS 侧「缓缓浮现（transition 非瞬时）」见
 * styles/__tests__/spec-visual-contract.test.ts（台账 #9 CSS 形态）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/** 条款断言不涉及的旁路组件/通道打桩（防无关模块进入测试面） */
vi.mock('@/components/left-panel/DraftCard', () => ({ DraftCard: () => null }));
vi.mock('@/components/left-panel/group-card/GroupDescEditor', () => ({ GroupDescEditor: () => null }));
vi.mock('@/lib/agent-actions', () => ({ sendUserMessage: vi.fn() }));

import { GroupCard } from '../left-panel/GroupCard';
import { sendUserMessage } from '@/lib/agent-actions';
import type { KeyElementGroup } from '@/types';

const noop = () => {};

function makeGroup(): KeyElementGroup {
  return {
    id: 'g1',
    title: '月球',
    drafts: [{ id: 'd1', label: '草稿 1', tag: '手动', mediaType: 'image', imgUrl: '', prompt: '' }],
  };
}

function setup() {
  return render(() => (
    <GroupCard
      group={makeGroup()}
      type="keyElement"
      index={1}
      dragOver={false}
      onDragStart={noop}
      onDragOver={noop}
      onDragLeave={noop}
      onDrop={noop}
      onDragEnd={noop}
      onContextMenu={noop}
    />
  ));
}

describe('故事板微调框悬停 300ms 浮现（台账 #9）', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sendUserMessage).mockClear();
  });
  afterEach(() => vi.useRealTimers());

  it('初始收起：微调框存在但未展开', () => {
    const { container } = setup();
    const box = container.querySelector('.card-adjust-box');
    expect(box).toBeTruthy();
    expect(box!.classList.contains('open')).toBe(false);
  });

  it('悬停草稿卡：即刻与 299ms 均不弹，满 300ms 浮现', () => {
    const { container } = setup();
    const wrap = container.querySelector('.draft-card-wrap') as HTMLElement;
    const box = container.querySelector('.card-adjust-box')!;

    fireEvent.mouseEnter(wrap);
    expect(box.classList.contains('open')).toBe(false);

    vi.advanceTimersByTime(299);
    expect(box.classList.contains('open')).toBe(false);

    vi.advanceTimersByTime(1);
    expect(box.classList.contains('open')).toBe(true);
  });

  it('300ms 内移出分组：挂表取消，之后不再浮现', () => {
    const { container } = setup();
    const wrap = container.querySelector('.draft-card-wrap') as HTMLElement;
    const groupEl = container.querySelector('.sb-group') as HTMLElement;
    const box = container.querySelector('.card-adjust-box')!;

    fireEvent.mouseEnter(wrap);
    fireEvent.mouseLeave(groupEl);
    vi.advanceTimersByTime(1000);
    expect(box.classList.contains('open')).toBe(false);
  });

  it('悬停标题区（非草稿卡）：不挂表，300ms 后也不浮现', () => {
    const { container } = setup();
    const title = container.querySelector('.sb-title') as HTMLElement;
    const box = container.querySelector('.card-adjust-box')!;

    fireEvent.mouseEnter(title);
    vi.advanceTimersByTime(1000);
    expect(box.classList.contains('open')).toBe(false);
  });

  it('浮现后输入意见并点「微调」：意见携带卡编号发出', () => {
    const { container } = setup();
    const wrap = container.querySelector('.draft-card-wrap') as HTMLElement;
    fireEvent.mouseEnter(wrap);
    vi.advanceTimersByTime(300);

    const input = container.querySelector('.card-adjust-input') as HTMLInputElement;
    fireEvent.input(input, { target: { value: '改亮一点' } });
    fireEvent.click(container.querySelector('.card-adjust-btn') as HTMLElement);

    expect(vi.mocked(sendUserMessage)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(sendUserMessage).mock.calls[0][0]).toContain('第 1-1 卡');
    expect(vi.mocked(sendUserMessage).mock.calls[0][0]).toContain('改亮一点');
  });
});
