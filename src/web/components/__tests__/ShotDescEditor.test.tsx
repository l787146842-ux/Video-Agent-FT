/**
 * ShotDescEditor 交互测试（对齐 Flova 批）：
 * ① 读态：keyElements 全集提及渲染为内联块（候选源为关键元素全集，不再局限 sceneRefs）；
 * ② 读态点块 = 跳转该关键元素；
 * ③ 双击进编辑态（contenteditable + 块内 ×）；
 * ④ 编辑态 × 删块 + 失焦保存：desc 序列化回纯文本、sceneRefs 同步减引用；
 * ⑤ Esc 放弃退出（不写库）。
 */
import { render, fireEvent } from '@solidjs/testing-library';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const renameGroupLocal = vi.fn();
const setSceneRefsLocal = vi.fn();
const jumpToElementByTitle = vi.fn();

vi.mock('@/stores/studio', () => ({
  state: { keyElements: [], shots: [], audioItems: [] },
  studioActions: {
    renameGroupLocal: (...args: unknown[]) => renameGroupLocal(...args),
    setSceneRefsLocal: (...args: unknown[]) => setSceneRefsLocal(...args),
    jumpToElementByTitle: (...args: unknown[]) => jumpToElementByTitle(...args),
  },
}));

import { state } from '@/stores/studio';
import { ShotDescEditor } from '../left-panel/group-card/ShotDescEditor';
import type { ShotGroup } from '@/types';

function makeGroup(desc: string, sceneRefs: string[]): ShotGroup {
  return { id: 'shot-1', desc, sceneRefs } as unknown as ShotGroup;
}

const tick = (ms = 60) => new Promise((r) => setTimeout(r, ms));

beforeEach(() => {
  renameGroupLocal.mockClear();
  setSceneRefsLocal.mockClear();
  jumpToElementByTitle.mockClear();
  state.keyElements = [
    { id: 'ke-1', title: '程心', drafts: [{ imgUrl: '/a/cx.png' }] },
    { id: 'ke-2', title: 'AA', drafts: [] },
    { id: 'ke-3', title: '曹彬', drafts: [] },
  ] as never;
});

describe('ShotDescEditor（分镜正文内联块与编辑）', () => {
  it('读态：keyElements 全集提及成块（不再局限 sceneRefs）', async () => {
    // sceneRefs 仅含 ke-1，但正文提及的「曹彬」同属 keyElements 全集 → 也成块
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 与曹彬对峙', ['ke-1'])} />
    ));
    await tick(0);
    const chips = [...container.querySelectorAll('.mention-chip')] as HTMLElement[];
    expect(chips.map((c) => c.dataset.name)).toEqual(['程心', '曹彬']);
  });

  it('读态点块跳转该关键元素', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 苏醒', ['ke-1'])} />
    ));
    await tick(0);
    const chip = container.querySelector('.mention-chip') as HTMLElement;
    fireEvent.click(chip);
    expect(jumpToElementByTitle).toHaveBeenCalledWith('程心');
  });

  it('双击进编辑态：contenteditable + 块内 ×', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 苏醒', ['ke-1'])} />
    ));
    await tick(0);
    fireEvent.dblClick(container.querySelector('.sb-design-body') as HTMLElement);
    await tick();
    const editor = container.querySelector('.sb-design-body--editing') as HTMLElement;
    expect(editor).not.toBeNull();
    expect(editor.getAttribute('contenteditable')).not.toBeNull();
    expect(editor.querySelector('.mention-chip .desc-ref-remove')).not.toBeNull();
  });

  it('双击正文内部文字（真实 click×2+dblclick 序列）也能进编辑', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 苏醒在舱内', ['ke-1'])} />
    ));
    await tick(0);
    const body = container.querySelector('.sb-design-body') as HTMLElement;
    // 双击内部文字节点（非 chip）：两次 click + dblclick 均应冒泡到 <p>
    fireEvent.click(body);
    fireEvent.click(body);
    fireEvent.dblClick(body);
    await tick();
    expect(container.querySelector('.sb-design-body--editing')).not.toBeNull();
  });

  it('单击展开延迟生效；双击时不触发展开切换（无布局抖动）', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 苏醒', ['ke-1'])} />
    ));
    await tick(0);
    const body = container.querySelector('.sb-design-body') as HTMLElement;
    expect(body.className).toContain('sb-design-body--collapsed');
    fireEvent.click(body);
    await tick(50);
    // 250ms 内仍是折叠态（dblclick 配对窗口）
    expect(body.className).toContain('sb-design-body--collapsed');
    await tick(260);
    expect(body.className).not.toContain('sb-design-body--collapsed');
  });

  it('编辑态 × 删块 + 失焦保存：desc 回纯文本、sceneRefs 同步减引用', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 与 AA 苏醒', ['ke-1', 'ke-2'])} />
    ));
    await tick(0);
    fireEvent.dblClick(container.querySelector('.sb-design-body') as HTMLElement);
    await tick();
    const editor = container.querySelector('.sb-design-body--editing') as HTMLElement;
    fireEvent.click(editor.querySelector('.desc-ref-remove') as HTMLElement);
    expect(editor.querySelectorAll('.mention-chip').length).toBe(1);
    fireEvent.blur(editor);
    await tick(220);
    expect(renameGroupLocal).toHaveBeenCalledWith('shot', 'shot-1', { desc: ' 与 AA 苏醒' });
    expect(setSceneRefsLocal).toHaveBeenCalledWith('shot-1', ['ke-2']);
  });

  it('Esc 放弃退出：不写库', async () => {
    const { container } = render(() => (
      <ShotDescEditor group={makeGroup('程心 苏醒', ['ke-1'])} />
    ));
    await tick(0);
    fireEvent.dblClick(container.querySelector('.sb-design-body') as HTMLElement);
    await tick();
    const editor = container.querySelector('.sb-design-body--editing') as HTMLElement;
    fireEvent.keyDown(editor, { key: 'Escape' });
    await tick(220);
    expect(container.querySelector('.sb-design-body--editing')).toBeNull();
    expect(renameGroupLocal).not.toHaveBeenCalled();
    expect(setSceneRefsLocal).not.toHaveBeenCalled();
  });
});
