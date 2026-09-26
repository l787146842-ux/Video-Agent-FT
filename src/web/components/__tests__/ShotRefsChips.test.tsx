/**
 * ShotRefsChips 交互测试（任务#9 前端棘轮回填 + 引用契约钉死）。
 *
 * 钉死契约：
 * ① chip 展示解析为关键元素标题（存 id 也显示标题，卡片可读性）；
 * ② × 移除经 setShotRefsLocal 全量替换式上抛（余下引用按字符串口径）；
 * ③ + 添加候选只列未引用元素；选中后追加上抛并收弹层；
 * ④ 候选耗尽时弹层显示空态文案（不误渲染空按钮列表）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const setShotRefsLocal = vi.fn();
const jumpToElementByTitle = vi.fn();

vi.mock('@/stores/studio', () => ({
  state: { keyElements: [] },
  studioActions: {
    setShotRefsLocal: (...args: unknown[]) => setShotRefsLocal(...args),
    jumpToElementByTitle: (...args: unknown[]) => jumpToElementByTitle(...args),
  },
}));

import { state } from '@/stores/studio';
import { ShotRefsChips } from '../left-panel/group-card/ShotRefsChips';
import type { ShotGroup } from '@/types';

function makeGroup(shotRefs: string[] = []): ShotGroup {
  return { id: 'shot-1', shotRefs } as unknown as ShotGroup;
}

beforeEach(() => {
  setShotRefsLocal.mockClear();
  jumpToElementByTitle.mockClear();
  // 2026-09-25：标题用**落库真实形态**（带 Element_ 前缀）。此前夹具用裸名，
  // 与裸名 ref 恰好逐字相等 ⇒ 掩盖了「裸名引用点不动」的生产事故（8888）。
  state.keyElements = [
    { id: 'ke-1', title: 'Element_少女' },
    { id: 'ke-2', title: 'Element_古宅' },
  ] as never;
});

describe('ShotRefsChips（引用展示与增删）', () => {
  it('引用按元素标题展示；点击跳转；× 移除全量替换上抛', async () => {
    const { container } = render(() => (
      <ShotRefsChips group={makeGroup(['ke-1', 'Element_古宅'])} />
    ));
    // id 与带前缀标题两种存储形态都解析为**裸名展示**（显示层剥容器前缀）
    const jumps = container.querySelectorAll('.shot-ref-jump');
    expect([...jumps].map((b) => b.textContent)).toEqual(['少女', '古宅']);
    // 点击跳转（按存储原值上抛，id 与标题两种形态均透传）
    await fireEvent.click(jumps[0]);
    expect(jumpToElementByTitle).toHaveBeenCalledWith('ke-1');
    // × 移除第一条：余下引用上抛
    await fireEvent.click(container.querySelectorAll('.shot-ref-remove')[0]);
    expect(setShotRefsLocal).toHaveBeenCalledWith('shot-1', ['Element_古宅']);
  });

  it('添加候选只列未引用元素；选中后追加并收弹层', async () => {
    const { container, getByText } = render(() => (
      <ShotRefsChips group={makeGroup(['ke-1'])} />
    ));
    await fireEvent.click(getByText('添加'));
    const items = container.querySelectorAll('.shot-ref-picker-item');
    expect([...items].map((b) => b.textContent)).toEqual(['古宅']); // 少女已引用不重复列
    await fireEvent.click(items[0]);
    // 添加候选按**元素原标题**上抛（带前缀，落库口径；显示层才剥前缀）
    expect(setShotRefsLocal).toHaveBeenCalledWith('shot-1', ['ke-1', 'Element_古宅']);
    expect(container.querySelector('.shot-ref-picker')).toBeNull(); // 收弹层
  });

  it('候选耗尽时空态文案；点选单外区域关闭弹层', async () => {
    state.keyElements = [{ id: 'ke-1', title: 'Element_少女' }] as never;
    const { container, getByText } = render(() => (
      <ShotRefsChips group={makeGroup(['Element_少女'])} />
    ));
    await fireEvent.click(getByText('添加'));
    expect(container.querySelector('.shot-ref-picker-empty')?.textContent)
      .toBe('没有可添加的关键元素');
    // 点选单外区域关闭弹层（createEffect 挂的 pointerdown 监听）
    await fireEvent.pointerDown(document.body, { bubbles: true });
    expect(container.querySelector('.shot-ref-picker')).toBeNull();
  });

  it('无引用时不渲染「场景:」标签行', () => {
    const { container } = render(() => <ShotRefsChips group={makeGroup([])} />);
    expect(container.querySelector('.shot-refs-label')).toBeNull();
  });

  it('存量同元素裸名+Element_ 双份显示去重保序留首（flova 对齐批 2026-09-17）', () => {
    const { container } = render(() => (
      <ShotRefsChips group={makeGroup(['少女', 'Element_少女', 'ke-1', 'Element_古宅'])} />
    ));
    const jumps = container.querySelectorAll('.shot-ref-jump');
    // 少女/Element_少女/ke-1 同解析标签「少女」→ 只留首份；古宅独立
    expect([...jumps].map((b) => b.textContent)).toEqual(['少女', '古宅']);
  });
});
