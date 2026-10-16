/**
 * Header 导航测试：顶栏导航（影视工作台 / 画布 / API 配置）+「影视工作台」回预览。
 * Router / 主题 / 项目切换 / 历史与任务入口全部打桩，
 * 只钉两件事：① 点击入口真的切状态（含 A 组件透传 onClick 的用法）；
 * ② 「子任务」已迁出顶栏（不再占导航频道）——故工作台页恒高亮、不互斥。
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

describe('Header 导航（子任务入口已迁出顶栏）', () => {
  it('顶栏不再渲染「子任务」文字入口（已迁至会话标签栏前方图标）', () => {
    const { queryByText } = renderHeader();
    expect(queryByText('子任务')).toBeNull();
  });

  it('初始（预览频道）：影视工作台高亮', () => {
    const { getByText } = renderHeader();
    expect(getByText('影视工作台').className).toContain('active');
  });

  it('子任务视图下「影视工作台」仍高亮（导航不再与子任务互斥）', () => {
    setState('middleView', 'subagents');
    const { getByText } = renderHeader();
    expect(getByText('影视工作台').className).toContain('active');
  });

  it('子任务视图下点「影视工作台」→ 中间面板切回预览', () => {
    setState('middleView', 'subagents');
    const { getByText } = renderHeader();
    fireEvent.click(getByText('影视工作台'));
    expect(state.middleView).toBe('preview');
    expect(getByText('影视工作台').className).toContain('active');
  });
});
