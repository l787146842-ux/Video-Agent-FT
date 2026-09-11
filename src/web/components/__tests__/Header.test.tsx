/**
 * Header 导航测试：顶栏「子任务」入口 / 「影视工作台」入口对偶切换 middleView。
 * Router / 主题 / 项目切换 / 历史与任务入口全部打桩，
 * 只钉两件事：① 点击入口真的切状态（含 A 组件透传 onClick 的用法）；
 * ② 导航组激活互斥（子任务频道激活时「影视工作台」不高亮，反之亦然）。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { JSX } from 'solid-js';

vi.mock('@solidjs/router', () => ({
  A: (props: { class?: string; onClick?: () => void; children?: JSX.Element }) => (
    <a class={props.class} onClick={() => props.onClick?.()}>{props.children}</a>
  ),
  useLocation: () => ({ pathname: '/' }),
}));
vi.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({ theme: () => 'dark', toggle: vi.fn() }),
}));
vi.mock('@/stores/history', () => ({
  historyState: { canUndo: false, canRedo: false },
  performUndo: vi.fn(),
  performRedo: vi.fn(),
}));
vi.mock('@/stores/generation-log', () => ({
  toggleGenLog: vi.fn(),
  genLogUnread: () => 0,
}));
vi.mock('@/stores/jobs', () => ({ toggleJobs: vi.fn() }));
vi.mock('../layout/ProjectSwitcher', () => ({ ProjectSwitcher: () => <div /> }));

import { Header } from '../layout/Header';
import { state, setState } from '@/stores/studio';

beforeEach(() => { setState('middleView', 'preview'); });
afterEach(() => { cleanup(); });

function renderHeader() {
  return render(() => <Header overlayMode={false} onToggleHeader={() => {}} />);
}

describe('Header 子任务入口 / 影视工作台入口', () => {
  it('初始（预览频道）：影视工作台高亮、子任务不高亮', () => {
    const { getByText } = renderHeader();
    expect(getByText('影视工作台').className).toContain('active');
    expect(getByText('子任务').className).not.toContain('active');
  });

  it('点「子任务」→ 中间面板切子任务；高亮互斥（影视工作台灭）', () => {
    const { getByText } = renderHeader();
    fireEvent.click(getByText('子任务'));
    expect(state.middleView).toBe('subagents');
    expect(getByText('子任务').className).toContain('active');
    expect(getByText('影视工作台').className).not.toContain('active');
  });

  it('子任务频道下点「影视工作台」→ 切回预览；高亮反转', () => {
    setState('middleView', 'subagents');
    const { getByText } = renderHeader();
    fireEvent.click(getByText('影视工作台'));
    expect(state.middleView).toBe('preview');
    expect(getByText('影视工作台').className).toContain('active');
    expect(getByText('子任务').className).not.toContain('active');
  });
});
