/**
 * desc-ref-utils 契约测试（对齐 Flova 批）：
 * ① resolveRefTitle 兼容 id/标题两种口径，未知值原样透传；
 * ② descChipNames 候选源 = keyElements 全集；每元素产原全称 + 归一裸名两形态，
 *    去重 + ≥2 字符守卫 + 长度降序（最长优先防重叠标题误切）；
 * ③ render/serialize roundtrip：\n\n 分段保留、块还原纯名（不带 @）；
 * ④ editable 块内产 × 删除钮，读态不产；有概念图产缩略图、无图纯名块；
 * ⑤ syncSceneRefsAfterEdit：旧 − 正文已消失提及 + @ 插入；无增删返回 null。
 */
import { describe, it, expect } from 'vitest';
import {
  resolveRefTitle, descChipNames, renderDescToDOM, serializeDescDOM, syncSceneRefsAfterEdit,
  stripCategoryPrefix,
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

  it('descChipNames 候选源为 keyElements 全集；去重并按长度降序', () => {
    // 传入的 sceneRefs 被忽略（候选不再依赖本镜 sceneRefs），全集产出
    const names = descChipNames({ sceneRefs: [] }, KES);
    expect(names).toEqual(['S1 星环号球形舱', '程心AA', '程心', 'AA']);
  });

  it('descChipNames 每元素产原全称 + 归一裸名；≥2 字符守卫剔除单字候选', () => {
    const kes = [
      { id: 'k1', title: '角色：程心' },  // 全称 + 裸名「程心」两种形态
      { id: 'k2', title: '道具1刀' },      // 裸名「刀」单字被 ≥2 守卫剔除，仅留全称
      { id: 'k3', title: '乙' },           // 单字全称本身被守卫剔除
    ];
    const names = descChipNames({ sceneRefs: [] }, kes);
    expect(names).toEqual(['角色：程心', '道具1刀', '程心']);
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

describe('stripCategoryPrefix（前端归一单一事实源，对齐后端契约）', () => {
  it('全角冒号分支：剥离类别前缀', () => {
    expect(stripCategoryPrefix('角色：程心')).toBe('程心');
    expect(stripCategoryPrefix('场景：星环号')).toBe('星环号');
  });

  it('半角冒号分支：剥离类别前缀', () => {
    expect(stripCategoryPrefix('道具:青龙偃月刀')).toBe('青龙偃月刀');
    expect(stripCategoryPrefix('人物:曹彬')).toBe('曹彬');
  });

  it('编号分支（类别+数字）：剥离前缀', () => {
    expect(stripCategoryPrefix('角色1程心')).toBe('程心');
    expect(stripCategoryPrefix('载具-2 星环号')).toBe('星环号');
    expect(stripCategoryPrefix('音频3背景声')).toBe('背景声');
  });

  it('可选前缀 元素/关键元素 一并剥离', () => {
    expect(stripCategoryPrefix('元素角色：程心')).toBe('程心');
    expect(stripCategoryPrefix('关键元素场景1星环号')).toBe('星环号');
  });

  it('剥后为空 → 返原文', () => {
    expect(stripCategoryPrefix('角色：')).toBe('角色：');
    expect(stripCategoryPrefix('场景1')).toBe('场景1');
  });

  it('剥后无中文 → 返原文', () => {
    expect(stripCategoryPrefix('角色：AA')).toBe('角色：AA');
    expect(stripCategoryPrefix('道具:S1')).toBe('道具:S1');
  });

  it('纯 ASCII / 无类别前缀 → 返原文', () => {
    expect(stripCategoryPrefix('AA')).toBe('AA');
    expect(stripCategoryPrefix('Role:John')).toBe('Role:John');
    expect(stripCategoryPrefix('程心')).toBe('程心');
  });

  it('空串 → 返空串', () => {
    expect(stripCategoryPrefix('')).toBe('');
  });
});
