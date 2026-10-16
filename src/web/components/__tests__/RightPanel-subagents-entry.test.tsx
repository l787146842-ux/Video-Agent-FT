/**
 * RightPanel 子任务入口（2026-10-16 用户裁决：自顶栏迁至会话标签栏最前方）。
 *
 * 钉死三件事：
 * ① 入口位于会话标签栏、**最前**（在全部会话标签之前），且仅图标（无文字）；
 * ② 点击为**开关**语义：预览 → 子任务视图；再点 → 回预览（对齐原顶栏入口的
 *    单向上行 + 本批新增的回程能力）；
 * ③ 闪烁判据 = 有子代理正在执行（subagentActivity().running）：running →
 *    带 .running 类与脉冲点；父 run_subagent 收尾（completed/failed）→ 停闪。
 *    判据取自 actor 域单点，不在此组件自行遍历。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// 三个重子件打桩（只钉入口本身）
vi.mock('../right-panel/ChatFeed', () => ({ ChatFeed: () => <div data-testid="feed-stub" /> }));
vi.mock('../right-panel/ChatInput', () => ({ ChatInput: () => <div data-testid="input-stub" /> }));
vi.mock('../right-panel/ChatSearchBar', () => ({ ChatSearchBar: () => <div /> }));

import RightPanel from '../right-panel/RightPanel';
import { state, setState } from '@/stores/studio';
import { setConvState } from '@/stores/conversations';
import { resetSubagentActors, subagentActorActions } from '@/stores/chat/subagent-actors';
import type { SseEvent, SseSubagentMeta } from '@/types';

const META: SseSubagentMeta = {
  cid: 'conv-sub-1', stage: 'script_analyze', label: '剧本分析', depth: 1,
};

function childToolStarted(id = 't1'): SseEvent {
  return { type: 'tool_started', id, name: 'read_state_group', summary: '读分组' } as SseEvent;
}

/** 父委派收尾帧（run_subagent 锚点；不带 subagent 标记） */
function delegateFinish(ok = true): SseEvent[] {
  return [
    { type: 'tool_started', id: 'anchor-1', name: 'run_subagent', summary: '委派' } as SseEvent,
    { type: 'tool_finished', id: 'anchor-1', ok } as SseEvent,
  ];
}

beforeEach(() => {
  setState({ middleView: 'preview' });
  setConvState({ list: [{ id: 'c1', title: '会话 1' }], activeId: 'c1' });
  resetSubagentActors();
});
afterEach(() => { cleanup(); });

describe('子任务入口：位置与形态', () => {
  it('位于会话标签栏、且在全部会话标签之前；仅图标（无文字「子任务」）', () => {
    const { getByTestId, queryByText, container } = render(() => <RightPanel />);
    const entry = getByTestId('subagents-entry');
    expect(entry).toBeTruthy();
    expect(queryByText('子任务')).toBeNull();   // 仅图标，不渲染文字标签
    // 最前：tabs 容器内第一个元素即入口
    const tabs = container.querySelector('.conv-tabs')!;
    expect(tabs.firstElementChild).toBe(entry);
    // 入口之后才是会话标签
    expect(entry.nextElementSibling?.textContent).toContain('会话 1');
  });
});

describe('子任务入口：点击 = 开关（切过去 / 再点回来）', () => {
  it('预览态点击 → 切子任务视图', () => {
    const { getByTestId } = render(() => <RightPanel />);
    fireEvent.click(getByTestId('subagents-entry'));
    expect(state.middleView).toBe('subagents');
  });

  it('子任务视图下再点 → 回预览（开关语义，本批新增回程）', () => {
    setState('middleView', 'subagents');
    const { getByTestId } = render(() => <RightPanel />);
    fireEvent.click(getByTestId('subagents-entry'));
    expect(state.middleView).toBe('preview');
  });

  it('开关可反复：预览 → 子任务 → 预览 → 子任务', () => {
    const { getByTestId } = render(() => <RightPanel />);
    const entry = getByTestId('subagents-entry');
    fireEvent.click(entry);
    expect(state.middleView).toBe('subagents');
    fireEvent.click(entry);
    expect(state.middleView).toBe('preview');
    fireEvent.click(entry);
    expect(state.middleView).toBe('subagents');
  });

  it('在子任务视图时带 active 标记（当前频道可见）', () => {
    setState('middleView', 'subagents');
    const { getByTestId } = render(() => <RightPanel />);
    expect(getByTestId('subagents-entry').className).toContain('active');
  });
});

describe('子任务入口：闪烁判据（有子代理执行则闪，收尾即停）', () => {
  it('无子代理活动 → 不闪（无 .running、无脉冲点）', () => {
    const { getByTestId } = render(() => <RightPanel />);
    const entry = getByTestId('subagents-entry');
    expect(entry.className).not.toContain('running');
    expect(entry.querySelector('.conv-subagents-pulse')).toBeNull();
  });

  it('子代理开始执行（首个子事件入账）→ 闪', () => {
    const { getByTestId } = render(() => <RightPanel />);
    subagentActorActions.applyChildEvent(META, childToolStarted());
    const entry = getByTestId('subagents-entry');
    expect(entry.className).toContain('running');
    expect(entry.querySelector('.conv-subagents-pulse')).toBeTruthy();
  });

  it('父委派收尾（成功）→ 停闪', () => {
    const { getByTestId } = render(() => <RightPanel />);
    subagentActorActions.applyChildEvent(META, childToolStarted());
    const entry = getByTestId('subagents-entry');
    expect(entry.className).toContain('running');
    // 父 run_subagent 收尾帧
    const [start, finish] = delegateFinish(true);
    subagentActorActions.applyDelegateEvent(start);
    subagentActorActions.applyDelegateEvent(finish);
    expect(entry.className).not.toContain('running');
    expect(entry.querySelector('.conv-subagents-pulse')).toBeNull();
  });

  it('委派失败收尾（已中断）同样停闪——「完成就停」含失败态', () => {
    const { getByTestId } = render(() => <RightPanel />);
    subagentActorActions.applyChildEvent(META, childToolStarted());
    const entry = getByTestId('subagents-entry');
    expect(entry.className).toContain('running');
    const [start, finish] = delegateFinish(false);
    subagentActorActions.applyDelegateEvent(start);
    subagentActorActions.applyDelegateEvent(finish);
    expect(entry.className).not.toContain('running');
  });

  it('多个子代理串行：前一个收尾后仍在跑的另一个继续闪', () => {
    const { getByTestId } = render(() => <RightPanel />);
    const entry = getByTestId('subagents-entry');
    // 第一委派：开跑 + 收尾（actor1 → completed）
    subagentActorActions.applyChildEvent(META, childToolStarted('t1'));
    const [s1, f1] = delegateFinish(true);
    subagentActorActions.applyDelegateEvent(s1);
    subagentActorActions.applyDelegateEvent(f1);
    expect(entry.className).not.toContain('running');
    // 第二委派开跑（新 cid，新锚点）：仍有子在跑 → 继续闪
    subagentActorActions.applyChildEvent({ ...META, cid: 'conv-sub-2' }, childToolStarted('t2'));
    expect(entry.className).toContain('running');
    // 第二委派收尾 → 全部收工 → 停闪
    const [s2, f2] = delegateFinish(true);
    subagentActorActions.applyDelegateEvent(s2);
    subagentActorActions.applyDelegateEvent(f2);
    expect(entry.className).not.toContain('running');
    expect(entry.querySelector('.conv-subagents-pulse')).toBeNull();
  });
});
