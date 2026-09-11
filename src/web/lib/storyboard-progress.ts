/**
 * 长任务阶段进度的结构化派生（体验增强：进度感）。
 *
 * 客观来源：故事板客观进度——与 prompts/shared/storyboard_progress.md 同口径：
 * 关键元素 / 分镜 / 音频三区各自「已有媒体的草稿数 / 草稿总数」，
 * 由前端故事板状态直接推导（媒体落位即完成，零猜测）。
 *
 * （推理轮次进度段已随阶段规则去代码化批退役，2026-09-10：主代理不再设
 *   步数上限，「第 N/M 轮」失去分母，status 事件的 max 参数同批不再下发。）
 */
import type { AnyGroup } from '@/types';

/** 单块故事板的客观进度（done = 已有媒体的草稿数） */
export interface BoardProgress {
  board: 'keyElements' | 'shots' | 'audioItems';
  done: number;
  total: number;
}

/** 草稿是否已有媒体落位（图/视频/音频任一地址即算完成） */
function draftHasMedia(draft: { imgUrl?: string; videoUrl?: string; audioUrl?: string }): boolean {
  return Boolean(draft.imgUrl || draft.videoUrl || draft.audioUrl);
}

function boardCount(groups: AnyGroup[]): { done: number; total: number } {
  let done = 0;
  let total = 0;
  for (const g of groups) {
    for (const d of g.drafts || []) {
      total += 1;
      if (draftHasMedia(d)) done += 1;
    }
  }
  return { done, total };
}

/**
 * 三区客观进度（顺序固定：关键元素 → 分镜 → 音频，
 * 与 storyboard_progress 模板行序一致）。
 */
export function deriveBoardProgress(boards: {
  keyElements: AnyGroup[]; shots: AnyGroup[]; audioItems: AnyGroup[];
}): BoardProgress[] {
  return ([
    ['keyElements', boards.keyElements],
    ['shots', boards.shots],
    ['audioItems', boards.audioItems],
  ] as const).map(([board, groups]) => ({ board, ...boardCount(groups) }));
}
