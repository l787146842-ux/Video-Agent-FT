/**
 * 批3 回归钉子（2026-09-23，Q4/Q6 用户裁决「引用记号必须能工作」）：
 * 钉死三条独立根因 + 前端方言渲染缺口——
 *
 *   R1 方括号被吞：`@[程心]` 的 `[ ]` 不得进入捕获名；
 *   R2 转义下划线：Skill 模板原样 `<<<image\_场景>>>` 必须命中；
 *   R3 裸名别名：分组标题 `Element_程心` 的裸名 `程心` 必须可引用；
 *   Q6② 前端渲染：`<<<image_名称>>>` 必须渲染为 chip（此前前端零匹配，
 *        而实跑 15/15 张提示词卡都带该记号 —— 「全是文字」的真因）。
 *
 * 对偶断言：未命中语义（去记号留文字）与超限行为必须保持不变。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderPromptToDOM } from '@/lib/prompt-ref-utils';

// vi.mock 会被提升到文件顶部，故共享桩必须用 vi.hoisted 一并提升
const { KES } = vi.hoisted(() => ({
  KES: [
    { id: 'ke-1', title: 'Element_程心', drafts: [{ id: 'd1', label: '角色三视图', mediaType: 'image', imgUrl: '/a/cx.png' }] },
    { id: 'ke-2', title: 'Element_星环号球形舱', drafts: [{ id: 'd2', label: '场景四视图', mediaType: 'image', imgUrl: '/a/s1.png' }] },
  ],
}));

/** 以最小 state 桩驱动 storyboardMediaMap（模块内 import 的 state） */
vi.mock('@/stores/studio', () => ({
  state: {
    keyElements: KES,
    shots: [],
    audioItems: [],
  },
}));

const { storyboardMediaMap, resolvePromptForGeneration, stripTypePrefix } = await import('@/lib/prompt-mentions');

describe('批3 · R3 裸名别名（写口补前缀，引用链必须同口径）', () => {
  it('stripTypePrefix 剥三个结构性前缀', () => {
    expect(stripTypePrefix('Element_程心')).toBe('程心');
    expect(stripTypePrefix('Shot_开场')).toBe('开场');
    expect(stripTypePrefix('Audio_配乐')).toBe('配乐');
  });

  it('媒体映射同时含前缀名与裸名（两写法都可用）', () => {
    const map = storyboardMediaMap();
    expect(map['Element_程心']).toBeTruthy();
    expect(map['程心']).toBeTruthy();
    expect(map['程心'].url).toBe('/a/cx.png');
  });

  it('裸名引用可挂上参考图（实跑 110 次 0 命中的根因）', () => {
    const r = resolvePromptForGeneration('<<<image_程心>>>', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
    expect(r.prompt).toContain('参考图1：程心');
  });

  it('带前缀写法向后兼容', () => {
    const r = resolvePromptForGeneration('<<<image_Element_程心>>>', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
  });
});

describe('批3 · R2 转义下划线（Skill 模板原样必须可用）', () => {
  it('`<<<image\\_程心>>>` 命中（Markdown 转义形态）', () => {
    const r = resolvePromptForGeneration('<<<image\\_程心>>>', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
    expect(r.prompt).not.toContain('<<<image\\_程心>>>');
  });

  it('Skill 模板整行原样可解析', () => {
    const line = '\\[场景\\]: <<<image\\_程心>>> — \\[当前光影基调描述\\]';
    const r = resolvePromptForGeneration(line, [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
    expect(r.prompt).toContain('参考图1：程心');
  });

  it('裸 image_ 形态仍可用（两形态同轨）', () => {
    const r = resolvePromptForGeneration('<<<image_程心>>>', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
  });
});

describe('批3 · R1 方括号被吞', () => {
  it('`@[程心]` 方括号不得进入名字且必须命中', () => {
    const r = resolvePromptForGeneration('@[程心]', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
    expect(r.prompt).toContain('参考图1：程心');
    expect(r.prompt).not.toContain('[程心]');
  });

  it('`@程心` 裸写法仍可用', () => {
    const r = resolvePromptForGeneration('@程心', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
  });
});

describe('批3 · 未命中与超限语义不变', () => {
  it('未命中 → 去掉记号、保留文字、不挂图', () => {
    const r = resolvePromptForGeneration('@不存在的角色', [], 5);
    expect(r.refs).toEqual([]);
    expect(r.prompt).toBe('不存在的角色');
  });

  it('超限 → 去记号留文字、不追加', () => {
    const r = resolvePromptForGeneration('@程心', ['/x1.png', '/x2.png'], 2);
    expect(r.refs).toEqual(['/x1.png', '/x2.png']);
    expect(r.prompt).toBe('程心');
  });
});

describe('批3 · Q6② 前端渲染 `<<<image_>>>`（此前零匹配）', () => {
  let el: HTMLElement;

  beforeEach(() => {
    el = document.createElement('div');
  });

  const refMap = {
    程心: { url: '/a/cx.png', type: 'image' as const },
  };

  it('`<<<image_程心>>>` 渲染为 chip（不再是一段纯文字）', () => {
    renderPromptToDOM(el, '<<<image_程心>>>', refMap);
    const chips = el.querySelectorAll('.mention-chip');
    expect(chips.length).toBe(1);
    expect(chips[0].getAttribute('data-name')).toBe('程心');
    expect(el.textContent).not.toContain('<<<');
  });

  it('转义形态 `<<<image\\_程心>>>` 同样渲染为 chip', () => {
    renderPromptToDOM(el, '<<<image\\_程心>>>', refMap);
    expect(el.querySelectorAll('.mention-chip').length).toBe(1);
  });

  it('`@程心` 与 `@[程心]` 渲染为 chip', () => {
    renderPromptToDOM(el, '@程心', refMap);
    expect(el.querySelectorAll('.mention-chip').length).toBe(1);
    const el2 = document.createElement('div');
    renderPromptToDOM(el2, '@[程心]', refMap);
    expect(el2.querySelectorAll('.mention-chip').length).toBe(1);
  });

  it('未命中记号保持原样文字（不误产 chip）', () => {
    renderPromptToDOM(el, '<<<image_未知>>>', refMap);
    expect(el.querySelectorAll('.mention-chip').length).toBe(0);
    expect(el.textContent).toContain('<<<image_未知>>>');
  });
});
