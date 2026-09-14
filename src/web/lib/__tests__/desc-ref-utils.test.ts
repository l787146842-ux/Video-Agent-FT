/**
 * desc-ref-utils 契约测试（对齐 Flova 批）：
 * ① resolveRefTitle 兼容 id/标题两种口径，未知值原样透传；
 * ② descChipNames 去重 + 长度降序（最长优先防重叠标题误切）；
 * ③ render/serialize roundtrip：\n\n 分段保留、块还原纯名（不带 @）；
 * ④ editable 块内产 × 删除钮，读态不产；有概念图产缩略图、无图纯名块；
 * ⑤ syncSceneRefsAfterEdit：旧 − 正文已消失提及 + @ 插入；无增删返回 null。
 */
import { describe, it, expect } from 'vitest';
import {
  resolveRefTitle, descChipNames, renderDescToDOM, serializeDescDOM, syncSceneRefsAfterEdit,
} from '@/lib/desc-ref-utils';

const KES = [
  { id: 'ke-1', title: '程心', drafts: [{ imgUrl: '/a/cx.png' }] },
  { id: 'ke-2', title: 'AA', drafts: [] },
  { id: 'ke-3', title: 'S1 星环号球形舱', drafts: [{ imgUrl: '/a/s1.png' }] },
  { id: 'ke-4', title: '程心AA', drafts: [] },
];

describe('desc-ref-utils', () => {
  it('resolveRefTitle 兼容 id 与标题口径；未知值原样透传', () => {
    expect(resolveRefTitle('ke-1', KES)).toBe('程心');
    expect(resolveRefTitle('AA', KES)).toBe('AA');
    expect(resolveRefTitle('不存在', KES)).toBe('不存在');
  });

  it('descChipNames 去重并按长度降序', () => {
    const names = descChipNames({ sceneRefs: ['ke-1', 'AA', 'ke-4', '程心'] }, KES);
    expect(names).toEqual(['程心AA', '程心', 'AA']);
  });

  it('render/serialize roundtrip：分段保留、块还原纯名', () => {
    const el = document.createElement('div');
    const text = '【空间锚点】程心 在舱内。\n\n【台词】AA：为什么？';
    renderDescToDOM(el, text, descChipNames({ sceneRefs: ['ke-1', 'ke-2'] }, KES), KES, false);
    const chips = [...el.querySelectorAll('.mention-chip')] as HTMLElement[];
    expect(chips.map((c) => c.dataset.name)).toEqual(['程心', 'AA']);
    // 有概念图 → 缩略图；无概念图 → 纯名块（无图标无图）
    expect(chips[0].querySelector('img')).not.toBeNull();
    expect(chips[1].querySelector('img, .mention-chip-icon')).toBeNull();
    expect(serializeDescDOM(el)).toBe(text);
  });

  it('editable 块内产 × 删除钮；读态不产', () => {
    const el = document.createElement('div');
    renderDescToDOM(el, '程心 苏醒。', ['程心'], KES, true);
    expect(el.querySelector('.mention-chip .desc-ref-remove')).not.toBeNull();
    const el2 = document.createElement('div');
    renderDescToDOM(el2, '程心 苏醒。', ['程心'], KES, false);
    expect(el2.querySelector('.desc-ref-remove')).toBeNull();
  });

  it('最长优先：重叠标题切成一个块', () => {
    const el = document.createElement('div');
    renderDescToDOM(
      el, '程心AA 在窗侧', descChipNames({ sceneRefs: ['ke-1', 'ke-4'] }, KES), KES, false,
    );
    const chips = [...el.querySelectorAll('.mention-chip')] as HTMLElement[];
    expect(chips.map((c) => c.dataset.name)).toEqual(['程心AA']);
  });

  it('syncSceneRefsAfterEdit：旧 − 消失提及 + @ 插入；无增删 null', () => {
    expect(syncSceneRefsAfterEdit(['ke-1', 'ke-2'], '程心 与 AA 都在', [], KES)).toBeNull();
    expect(syncSceneRefsAfterEdit(['ke-1', 'ke-2'], '只剩 程心', [], KES)).toEqual(['ke-1']);
    expect(syncSceneRefsAfterEdit(['ke-1'], '程心 与曹彬？', ['曹彬'], KES))
      .toEqual(['ke-1', '曹彬']);
  });
});
