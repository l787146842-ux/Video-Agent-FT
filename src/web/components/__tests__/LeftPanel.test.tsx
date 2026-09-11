/**
 * 左栏容器（LeftPanel）测试：
 * ① 子任务入口已迁至顶栏 → 左栏只保留「故事板 / 未归类素材」两个 Tab；
 * ② 点击左栏任意处（内容区 / Tab 按钮）→ 中间面板切回预览（middleView='preview'）。
 * 子视图全部打桩，只钉本组件编排与点击回预览行为。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../left-panel/StoryboardView', () => ({
  StoryboardView: () => <div data-testid="sb-stub" />,
}));
vi.mock('../left-panel/UncategorizedView', () => ({
  UncategorizedView: () => <div data-testid="uc-stub" />,
}));
vi.mock('../left-panel/SnapshotHistoryBar', () => ({ SnapshotHistoryBar: () => null }));
vi.mock('../left-panel/BoardConflictPanel', () => ({ BoardConflictPanel: () => null }));

import LeftPanel from '../left-panel/LeftPanel';
import { state, setState } from '@/stores/studio';

beforeEach(() => {
  setState({ leftTab: 'storyboard', middleView: 'preview' });
});
afterEach(() => { cleanup(); });

describe('LeftPanel', () => {
  it('仅两个 Tab：故事板 / 未归类素材（子任务入口已迁顶栏）', () => {
    const { getByText, queryByText } = render(() => <LeftPanel />);
    expect(getByText('故事板')).toBeTruthy();
    expect(getByText('未归类素材')).toBeTruthy();
    expect(queryByText('子任务')).toBeNull();
  });

  it('点击左栏内容区任意处 → 中间面板切回预览', () => {
    setState('middleView', 'subagents');
    const { getByTestId } = render(() => <LeftPanel />);
    fireEvent.click(getByTestId('sb-stub'));
    expect(state.middleView).toBe('preview');
  });

  it('点击左栏 Tab 按钮同样回预览（且正常切 Tab）', () => {
    setState('middleView', 'subagents');
    const { getByText } = render(() => <LeftPanel />);
    fireEvent.click(getByText('未归类素材'));
    expect(state.leftTab).toBe('uncategorized');
    expect(state.middleView).toBe('preview');
  });
});
