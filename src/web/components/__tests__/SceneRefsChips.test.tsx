/**
 * SceneRefsChips 交互测试（任务#9 前端棘轮回填 + 场景引用契约钉死）。
 *
 * 钉死契约：
 * ① chip 展示解析为关键元素标题（存 id 也显示标题，卡片可读性）；
 * ② × 移除经 setSceneRefsLocal 全量替换式上抛（余下引用按字符串口径）；
 * ③ + 添加候选只列未引用元素；选中后追加上抛并收弹层；
 * ④ 候选耗尽时弹层显示空态文案（不误渲染空按钮列表）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const setSceneRefsLocal = vi.fn();
const jumpToElementByTitle = vi.fn();

vi.mock('@/stores/studio', () => ({
  state: { keyElements: [] },
  studioActions: {
    setSceneRefsLocal: (...args: unknown[]) => setSceneRefsLocal(...args),
    jumpToElementByTitle: (...args: unknown[]) => jumpToElementByTitle(...args),
  },
}));

import { state } from '@/stores/studio';
import { SceneRefsChips } from '../left-panel/group-card/SceneRefsChips';
import type { ShotGroup } from '@/types';

function makeGroup(sceneRefs: string[] = []): ShotGroup {
  return { id: 'shot-1', sceneRefs } as unknown as ShotGroup;
}

beforeEach(() => {
  setSceneRefsLocal.mockClear();
  jumpToElementByTitle.mockClear();
  state.keyElements = [
    { id: 'ke-1', title: '少女' },
    { id: 'ke-2', title: '古宅' },
  ] as never;
});

describe('SceneRefsChips（场景引用展示与增删）', () => {
  it('引用按元素标题展示；点击跳转；× 移除全量替换上抛', async () => {
    const { container } = render(() => (
      <SceneRefsChips group={makeGroup(['ke-1', '古宅'])} />
    ));
    // id 与标题两种存储形态都解析为标题展示
    const jumps = container.querySelectorAll('.scene-ref-jump');
    expect([...jumps].map((b) => b.textContent)).toEqual(['少女', '古宅']);
    // 点击跳转（按存储原值上抛，id 与标题两种形态均透传）
    await fireEvent.click(jumps[0]);
    expect(jumpToElementByTitle).toHaveBeenCalledWith('ke-1');
    // × 移除第一条：余下引用上抛
    await fireEvent.click(container.querySelectorAll('.scene-ref-remove')[0]);
    expect(setSceneRefsLocal).toHaveBeenCalledWith('shot-1', ['古宅']);
  });

  it('添加候选只列未引用元素；选中后追加并收弹层', async () => {
    const { container, getByText } = render(() => (
      <SceneRefsChips group={makeGroup(['ke-1'])} />
    ));
    await fireEvent.click(getByText('添加'));
    const items = container.querySelectorAll('.scene-ref-picker-item');
    expect([...items].map((b) => b.textContent)).toEqual(['古宅']); // 少女已引用不重复列
    await fireEvent.click(items[0]);
    expect(setSceneRefsLocal).toHaveBeenCalledWith('shot-1', ['ke-1', '古宅']);
    expect(container.querySelector('.scene-ref-picker')).toBeNull(); // 收弹层
  });

  it('候选耗尽时空态文案；点选单外区域关闭弹层', async () => {
    state.keyElements = [{ id: 'ke-1', title: '少女' }] as never;
    const { container, getByText } = render(() => (
      <SceneRefsChips group={makeGroup(['少女'])} />
    ));
    await fireEvent.click(getByText('添加'));
    expect(container.querySelector('.scene-ref-picker-empty')?.textContent)
      .toBe('没有可添加的关键元素');
    // 点选单外区域关闭弹层（createEffect 挂的 pointerdown 监听）
    await fireEvent.pointerDown(document.body, { bubbles: true });
    expect(container.querySelector('.scene-ref-picker')).toBeNull();
  });

  it('无引用时不渲染「场景:」标签行', () => {
    const { container } = render(() => <SceneRefsChips group={makeGroup([])} />);
    expect(container.querySelector('.scene-refs-label')).toBeNull();
  });
});
