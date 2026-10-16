/**
 * 左栏容器（LeftPanel）测试：
 * ① 子任务入口在会话标签栏（不在左栏）→ 左栏只保留「故事板 / 未归类素材」两个 Tab；
 * ② **2026-10-16 用户裁决**：中间面板为子任务视图时，点左栏**不再**切回预览——
 *    页签、内容区空白、版本栏一律保持当前视图不动；只有草稿卡/素材卡手势才回预览
 *    （卡片手势断言见 DraftCard/AssetCard 归属的用例）。
 * 子视图全部打桩，只钉本组件编排与「不再 catch-all 回预览」这一行为反转。
 */
import { render, fireEvent, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../left-panel/StoryboardView', () => ({
  StoryboardView: () => <div data-testid="sb-stub" />,
}));
vi.mock('../left-panel/UncategorizedView', () => ({
  UncategorizedView: () => <div data-testid="uc-stub" />,
}));
vi.mock('../left-panel/SnapshotHistoryBar', () => ({
  SnapshotHistoryBar: () => <div data-testid="snap-stub" />,
}));
vi.mock('../left-panel/BoardConflictPanel', () => ({ BoardConflictPanel: () => null }));

import LeftPanel from '../left-panel/LeftPanel';
import { state, setState } from '@/stores/studio';

beforeEach(() => {
  setState({ leftTab: 'storyboard', middleView: 'preview' });
});
afterEach(() => { cleanup(); });

describe('LeftPanel', () => {
  it('仅两个 Tab：故事板 / 未归类素材（子任务入口在会话标签栏）', () => {
    const { getByText, queryByText } = render(() => <LeftPanel />);
    expect(getByText('故事板')).toBeTruthy();
    expect(getByText('未归类素材')).toBeTruthy();
    expect(queryByText('子任务')).toBeNull();
  });

  it('点内容区空白处 → 保持子任务视图（不再 catch-all 回预览）', () => {
    setState('middleView', 'subagents');
    const { getByTestId } = render(() => <LeftPanel />);
    fireEvent.click(getByTestId('sb-stub'));
    expect(state.middleView).toBe('subagents');
  });

  it('点左栏 Tab 按钮 → 正常切 Tab，但视图不切回预览', () => {
    setState('middleView', 'subagents');
    const { getByText } = render(() => <LeftPanel />);
    fireEvent.click(getByText('未归类素材'));
    expect(state.leftTab).toBe('uncategorized');
    expect(state.middleView).toBe('subagents');
  });

  it('点版本栏（快照条）→ 同样保持子任务视图', () => {
    setState('middleView', 'subagents');
    const { getByTestId } = render(() => <LeftPanel />);
    fireEvent.click(getByTestId('snap-stub'));
    expect(state.middleView).toBe('subagents');
  });

  it('预览态下点左栏任意处仍是预览（视图本身不变）', () => {
    const { getByTestId } = render(() => <LeftPanel />);
    fireEvent.click(getByTestId('sb-stub'));
    expect(state.middleView).toBe('preview');
  });
});
