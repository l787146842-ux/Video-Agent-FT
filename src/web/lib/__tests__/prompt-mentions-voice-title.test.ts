/**
 * 2026-10-16 音色抢名批（用户裁决「先写引用、音频出来自动解析」配套）前端钉子。
 *
 * 病灶：音色卡（mediaType=audio）与角色设定图同住一个 keyElement 组，而组标题
 * 只登记「该组第一张有媒体的卡」——音色卡排在前面时（9999 实测「音色·程心」在
 * 「设定图·程心」之前）音频抢走组标题 ⇒ `@程心` 解析成**参考音频**而非角色图。
 * 后果：音频一旦落地，全篇 `@角色名` 集体从「角色的脸」变成「角色的声音」。
 *
 * 本文件与后端 `tests/unit/test_prompt_refs.py` 同名四条对偶（P1：前后端同契约）：
 *   ① 音频不抢组标题（@角色名 → 角色图）
 *   ② 音色卡仍按 label 可达（@音色·名称 → 音频）
 *   ③ 纯音色卡组仍可由组标题兜底（防静默降级）
 *   ④ 图未出图时组标题仍不落到音频（防时间窗复发）
 */
import { describe, it, expect, vi } from 'vitest';

/** 程心组：**音色卡在设定图之前**（9999 实测顺序），两者都有媒体 */
const VOICE_FIRST = [
  {
    id: 'ke-1', title: 'Element_程心',
    drafts: [
      { id: 'd1', label: '音色·程心', mediaType: 'audio', audioType: 'voice', audioUrl: '/a/cx.mp3' },
      { id: 'd2', label: '设定图·程心', mediaType: 'image', imgUrl: '/a/cx.png' },
    ],
  },
];

/** 纯音色卡组（4444 实测形状：Element_AA 只有一张 voice 卡） */
const VOICE_ONLY = [
  {
    id: 'ke-2', title: 'Element_AA',
    drafts: [
      { id: 'd3', label: '音色·AA', mediaType: 'audio', audioType: 'voice', audioUrl: '/a/aa.mp3' },
    ],
  },
];

/** 程心组但设定图**尚未出图**（卡在、URL 空） */
const IMAGE_NOT_YET = [
  {
    id: 'ke-1', title: 'Element_程心',
    drafts: [
      { id: 'd1', label: '音色·程心', mediaType: 'audio', audioType: 'voice', audioUrl: '/a/cx.mp3' },
      { id: 'd2', label: '设定图·程心', mediaType: 'image', imgUrl: '' },
    ],
  },
];

async function loadWith(keyElements: unknown[]) {
  vi.resetModules();
  vi.doMock('@/stores/studio', () => ({
    state: { keyElements, shots: [], audioItems: [] },
  }));
  return import('@/lib/prompt-mentions');
}

describe('2026-10-16 音色抢名批 · 音频不得抢占关键元素组标题', () => {
  it('① @角色名 必须解析到角色设定图（不是音频）', async () => {
    const { storyboardMediaMap, resolvePromptForGeneration } = await loadWith(VOICE_FIRST);
    const map = storyboardMediaMap();
    expect(map['程心'].kind).toBe('image');
    expect(map['程心'].url).toBe('/a/cx.png');

    const r = resolvePromptForGeneration('[角色]: @程心 —— 站在舱内', [], 5);
    expect(r.refs).toEqual(['/a/cx.png']);
    expect(r.prompt).toContain('参考图1：程心');
  });

  it('② 音色卡仍可用自身 label 引用到音频', async () => {
    const { storyboardMediaMap, resolvePromptForGeneration } = await loadWith(VOICE_FIRST);
    expect(storyboardMediaMap()['音色·程心'].kind).toBe('audio');

    const r = resolvePromptForGeneration('@音色·程心', [], 5);
    expect(r.refs).toEqual(['/a/cx.mp3']);
    expect(r.prompt).toContain('参考音频1：音色·程心');
  });

  it('③ 纯音色卡组：组标题兜底给音频（防静默去记号留文字）', async () => {
    const { storyboardMediaMap, resolvePromptForGeneration } = await loadWith(VOICE_ONLY);
    const map = storyboardMediaMap();
    expect(map['AA'].kind).toBe('audio');

    const r = resolvePromptForGeneration('@AA', [], 5);
    expect(r.refs).toEqual(['/a/aa.mp3']);
  });

  it('④ 设定图未出图时，组标题仍不落到音频（防时间窗复发）', async () => {
    const { storyboardMediaMap } = await loadWith(IMAGE_NOT_YET);
    const map = storyboardMediaMap();
    // 图未出：组标题暂不登记（空 url 不登记），但不得被音频占走
    expect(map['程心']).toBeUndefined();
    // 音色卡仍按 label 可达
    expect(map['音色·程心'].kind).toBe('audio');
  });

  it('⑤ @ 面板显示名同规则：音色卡不借走组标题', async () => {
    const { storyboardMediaList } = await loadWith(VOICE_FIRST);
    const items = storyboardMediaList();
    const audio = items.find((i) => i.url === '/a/cx.mp3');
    const image = items.find((i) => i.url === '/a/cx.png');
    expect(image?.name).toBe('Element_程心');
    expect(audio?.name).toBe('音色·程心'); // 不得是 'Element_程心'
  });
});
