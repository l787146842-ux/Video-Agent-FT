/**
 * 长任务阶段进度派生测试：
 * ① parseRoundParams——status 事件 {step,max} 提取的白名单与数值护栏；
 * ② deriveBoardProgress——故事板三区「已有媒体草稿/草稿总数」客观口径；
 * ③ roundPercent——百分比钳制。
 */
import { describe, it, expect } from 'vitest';
import {
  parseRoundParams, deriveBoardProgress, roundPercent,
} from '@/lib/storyboard-progress';
import type { AnyGroup, KeyElementGroup } from '@/types';

describe('parseRoundParams（status 事件轮次进度提取）', () => {
  it('白名单键 + 合法参数 → 结构化进度', () => {
    expect(parseRoundParams('agent.roundThinking', { prev: 1, step: 2, max: 5 }))
      .toEqual({ step: 2, max: 5 });
    expect(parseRoundParams('agent.roundStart', { step: 3, max: 8 }))
      .toEqual({ step: 3, max: 8 });
  });

  it('非轮次键 / 缺参数 / 非法数值一律返回 null（不污染进度条）', () => {
    expect(parseRoundParams('agent.planning', { step: 1, max: 2 })).toBeNull();
    expect(parseRoundParams(undefined, { step: 1, max: 2 })).toBeNull();
    expect(parseRoundParams('agent.roundThinking', undefined)).toBeNull();
    expect(parseRoundParams('agent.roundThinking', { step: 'x', max: 2 })).toBeNull();
    expect(parseRoundParams('agent.roundThinking', { step: 0, max: 5 })).toBeNull();
    expect(parseRoundParams('agent.roundThinking', { step: 2, max: -1 })).toBeNull();
  });

  it('字符串数值参数可解析（后端 JSON 数字/字符串均兼容）', () => {
    expect(parseRoundParams('agent.roundThinking', { step: '2', max: '4' }))
      .toEqual({ step: 2, max: 4 });
  });
});

/** 构造分组：drafts 仅保留进度派生关心的字段 */
function groups(mediaCount: number, bareCount: number): AnyGroup[] {
  const drafts = [
    ...Array.from({ length: mediaCount }, (_, i) => ({
      id: `m${i}`, label: `d${i}`, mediaType: 'image' as const, imgUrl: `/img/${i}.png`,
    })),
    ...Array.from({ length: bareCount }, (_, i) => ({
      id: `b${i}`, label: `b${i}`, mediaType: 'image' as const,
    })),
  ];
  return [{ id: 'g1', title: '组1', drafts }] as KeyElementGroup[];
}

describe('deriveBoardProgress（故事板客观进度）', () => {
  it('三区顺序固定，done = 已有媒体的草稿数', () => {
    const out = deriveBoardProgress({
      keyElements: groups(2, 1),
      shots: groups(0, 3),
      audioItems: [],
    });
    expect(out.map((b) => b.board)).toEqual(['keyElements', 'shots', 'audioItems']);
    expect(out[0]).toEqual({ board: 'keyElements', done: 2, total: 3 });
    expect(out[1]).toEqual({ board: 'shots', done: 0, total: 3 });
    expect(out[2]).toEqual({ board: 'audioItems', done: 0, total: 0 });
  });

  it('视频/音频地址同样计入完成（媒体落位即完成，不区分媒体类型）', () => {
    const shots = [{
      id: 's', title: '镜', drafts: [
        { id: 'v', label: 'v', mediaType: 'video', videoUrl: '/v.mp4' },
        { id: 'a', label: 'a', mediaType: 'audio', audioUrl: '/a.mp3' },
      ],
    }] as AnyGroup[];
    const out = deriveBoardProgress({ keyElements: [], shots, audioItems: [] });
    expect(out[1]).toEqual({ board: 'shots', done: 2, total: 2 });
  });

  it('多组合并计数（跨组草稿同口径）', () => {
    const ke = [
      ...groups(1, 0),
      { id: 'g2', title: '组2', drafts: [{ id: 'x', label: 'x', mediaType: 'image' as const }] },
    ] as AnyGroup[];
    const out = deriveBoardProgress({ keyElements: ke, shots: [], audioItems: [] });
    expect(out[0]).toEqual({ board: 'keyElements', done: 1, total: 2 });
  });
});

describe('roundPercent（百分比钳制）', () => {
  it('正常区间按比例取整', () => {
    expect(roundPercent({ step: 1, max: 4 })).toBe(25);
    expect(roundPercent({ step: 4, max: 4 })).toBe(100);
  });

  it('null / 超界一律钳制在 0-100', () => {
    expect(roundPercent(null)).toBe(0);
    expect(roundPercent({ step: 0, max: 0 })).toBe(0);
    expect(roundPercent({ step: 9, max: 4 })).toBe(100);
  });
});
