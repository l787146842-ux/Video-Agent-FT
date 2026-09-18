/**
 * desc-ref-utils 契约测试（对齐 Flova 批）：
 * ① resolveRefTitle 兼容 id/标题两种口径，未知值原样透传；
 * ② descChipNames 候选源 = keyElements 全集；每元素产原全称 + 归一名字两形态，
 *    去重 + ≥2 字符守卫 + 长度降序（最长优先防重叠标题误切）；
 * ③ render/serialize roundtrip：\n\n 分段保留、块还原纯名（不带 @）；
 * ④ editable 块内产 × 删除钮，读态不产；有概念图产缩略图、无图纯名块；
 * ⑤ syncSceneRefsAfterEdit：旧 − 正文已消失提及 + @ 插入；无增删返回 null。
 */
import { describe, it, expect } from 'vitest';
import {
  resolveRefTitle, descChipNames, renderDescToDOM, serializeDescDOM, syncSceneRefsAfterEdit,
  stripTypePrefix, normalizeDisplayTitle, normalizeDisplayGroupTitle, canonicalGroupTitle,
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

  it('descChipNames 每元素产原全称 + 归一名字；≥2 字符守卫剔除单字候选', () => {
    const kes = [
      { id: 'k1', title: 'Element_程心' },  // 全称 + 名字「程心」两种形态
      { id: 'k2', title: 'Element_刀' },    // 名字「刀」单字被 ≥2 守卫剔除，仅留全称
      { id: 'k3', title: '乙' },           // 单字全称本身被守卫剔除
    ];
    const names = descChipNames({ sceneRefs: [] }, kes);
    expect(names).toEqual(['Element_程心', 'Element_刀', '程心']);
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

  it('syncSceneRefsAfterEdit auto 源：正文裸名提及自动补绑（K4 批提及即绑定）', () => {
    const kes = [
      { id: 'ke-1', title: 'Element_程心', drafts: [] },
      { id: 'ke-2', title: 'S1 星环号球形舱', drafts: [] },
    ];
    // prevRefs 空且无 @ 插入：正文名字提及自动补绑（存储口径 = 元素原标题，最长优先）
    expect(syncSceneRefsAfterEdit([], '程心 在 S1 星环号球形舱 内苏醒', [], kes))
      .toEqual(['S1 星环号球形舱', 'Element_程心']);
    // 已绑引用不重复补绑；无增删返回 null
    expect(syncSceneRefsAfterEdit(['ke-1'], '程心 苏醒', [], kes)).toBeNull();
  });
});

describe('stripTypePrefix（前端归一单一事实源，对齐后端 strip_type_prefix）', () => {
  it('三个容器类型前缀剥离显名字', () => {
    expect(stripTypePrefix('Element_程心')).toBe('程心');
    expect(stripTypePrefix('Shot_开场')).toBe('开场');
    expect(stripTypePrefix('Audio_配乐')).toBe('配乐');
  });

  it('纯结构性无词表翻译（2026-09-17 对齐 flova 裁决）：中文类别前缀属名字原样', () => {
    expect(stripTypePrefix('角色-程心')).toBe('角色-程心');
    expect(stripTypePrefix('角色：程心')).toBe('角色：程心');
    expect(stripTypePrefix('程心')).toBe('程心');
    expect(stripTypePrefix('AA')).toBe('AA');
  });

  it('空串 → 返空串', () => {
    expect(stripTypePrefix('')).toBe('');
  });
});

describe('canonicalGroupTitle（2026-09-17 裁决：写口幂等补容器类型前缀）', () => {
  it('名字原样补前缀；规范前缀输入幂等', () => {
    expect(canonicalGroupTitle('程心', 'keyElement')).toBe('Element_程心');
    expect(canonicalGroupTitle('Element_程心', 'keyElement')).toBe('Element_程心');
    expect(canonicalGroupTitle('开场', 'shot')).toBe('Shot_开场');
    expect(canonicalGroupTitle('配乐', 'audio')).toBe('Audio_配乐');
  });

  it('无词表翻译：中文类别前缀属名字一部分', () => {
    expect(canonicalGroupTitle('角色-程心', 'keyElement')).toBe('Element_角色-程心');
  });

  it('空串 → 空串', () => {
    expect(canonicalGroupTitle('', 'keyElement')).toBe('');
  });
});

describe('normalizeDisplayTitle（显示层只剥容器类型前缀，其余原样）', () => {
  it('剥容器类型前缀', () => {
    expect(normalizeDisplayTitle('Element_程心')).toBe('程心');
    expect(normalizeDisplayTitle('Shot_开场')).toBe('开场');
  });

  it('无类型前缀标题原样（名字 = 模型原文，平台不二次清洗）', () => {
    expect(normalizeDisplayTitle('Element_月球_基地')).toBe('月球_基地');
    expect(normalizeDisplayTitle('S1 星环号球形舱')).toBe('S1 星环号球形舱');
    expect(normalizeDisplayTitle('AA（双A）')).toBe('AA（双A）');
    expect(normalizeDisplayTitle('角色-程心')).toBe('角色-程心');
    expect(normalizeDisplayTitle('程心')).toBe('程心');
    expect(normalizeDisplayTitle('')).toBe('');
  });
});

describe('normalizeDisplayGroupTitle（flova 对齐批 2026-09-17：组标题剥存量镜号/场号 leading 令牌）', () => {
  it('剥容器前缀 + 迭代剥镜号/场号令牌', () => {
    expect(normalizeDisplayGroupTitle('Shot_01 场一·苏醒与木星窗外')).toBe('苏醒与木星窗外');
    expect(normalizeDisplayGroupTitle('Shot_S1 · 末日宣告/星环号球形舱')).toBe('末日宣告/星环号球形舱');
    expect(normalizeDisplayGroupTitle('S02·曹彬来电')).toBe('曹彬来电');
    expect(normalizeDisplayGroupTitle('01 开场')).toBe('开场');
  });

  it('守卫：数字开头元素名/年份不误剥；纯描述标题原样', () => {
    expect(normalizeDisplayGroupTitle('Element_二维空间平面')).toBe('二维空间平面');
    expect(normalizeDisplayGroupTitle('2D空间平面')).toBe('2D空间平面');
    expect(normalizeDisplayGroupTitle('1942年的街')).toBe('1942年的街');
    expect(normalizeDisplayGroupTitle('星环号苏醒与掩体失效')).toBe('星环号苏醒与掩体失效');
  });
});
