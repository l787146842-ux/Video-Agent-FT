/**
 * 中间面板双视图测试：
 * ① middleView='preview'（默认）→ 渲染预览框三件套（预览/提示词/参数），不渲染子任务面板；
 * ② middleView='subagents' → 整个中间面板切为子任务面板，预览三件套全部卸载。
 * 四个重子件全部打桩，只钉 Show 分支编排。
 */
import { render, cleanup } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../middle-panel/MediaViewer', () => ({
  MediaViewer: () => <div data-testid="media-viewer-stub" />,
}));
vi.mock('../middle-panel/PromptEditor', () => ({
  PromptEditor: () => <div data-testid="prompt-editor-stub" />,
}));
vi.mock('../middle-panel/ParamControls', () => ({
  ParamControls: () => <div data-testid="param-controls-stub" />,
}));
vi.mock('../middle-panel/SubagentRail', () => ({
  SubagentRail: () => <div data-testid="subagent-rail-stub" />,
}));

import MiddlePanel from '../middle-panel/MiddlePanel';
import { setState } from '@/stores/studio';

beforeEach(() => {
  setState({ middleView: 'preview', isPromptCollapsed: false });
});
afterEach(() => { cleanup(); });

describe('MiddlePanel 双视图', () => {
  it('默认预览视图：渲染预览框三件套，不渲染子任务面板', () => {
    const { getByTestId, queryByTestId } = render(() => <MiddlePanel />);
    expect(getByTestId('media-viewer-stub')).toBeTruthy();
    expect(getByTestId('prompt-editor-stub')).toBeTruthy();
    expect(getByTestId('param-controls-stub')).toBeTruthy();
    expect(queryByTestId('subagent-rail-stub')).toBeNull();
  });

  it('子任务视图：整个中间面板切为子任务面板（预览三件套卸载）', () => {
    setState('middleView', 'subagents');
    const { getByTestId, queryByTestId } = render(() => <MiddlePanel />);
    expect(getByTestId('subagent-rail-stub')).toBeTruthy();
    expect(queryByTestId('media-viewer-stub')).toBeNull();
    expect(queryByTestId('prompt-editor-stub')).toBeNull();
    expect(queryByTestId('param-controls-stub')).toBeNull();
  });
});
