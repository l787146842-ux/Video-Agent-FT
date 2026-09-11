/**
 * 长任务阶段进度派生测试：
 * ① deriveBoardProgress——故事板三区「已有媒体草稿/草稿总数」客观口径；
 * （推理轮次进度段已随阶段规则去代码化批退役，2026-09-10：
 *   parseRoundParams / roundPercent 同批删除。）
 */
import { describe, it, expect } from 'vitest';
import { deriveBoardProgress } from '@/lib/storyboard-progress';
import type { AnyGroup, KeyElementGroup } from '@/types';

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
