/**
 * 长任务阶段进度的结构化派生（体验增强：进度感）。
 *
 * 两条客观来源，不依赖模型自报：
 * 1. 推理轮次进度——后端 status 事件（agent.roundStart / agent.roundThinking）
 *    携带 {step, max} 数值参数，parseRoundParams 提取为结构化进度；
 * 2. 故事板客观进度——与 prompts/shared/storyboard_progress.md 同口径：
 *    关键元素 / 分镜 / 音频三区各自「已有媒体的草稿数 / 草稿总数」，
 *    由前端故事板状态直接推导（媒体落位即完成，零猜测）。
 */
import type { AnyGroup } from '@/types';

/** 推理轮次进度（status 事件参数提取结果） */
export interface RoundProgress { step: number; max: number; }

/** 携带轮次进度的 status 事件键（后端 planner / agent_loop 下发） */
const ROUND_STATUS_KEYS = new Set(['agent.roundStart', 'agent.roundThinking']);

/**
 * 从 status 事件提取轮次进度：仅认白名单键 + 合法数值参数；
 * step/max 缺失或非有限正数返回 null（不污染进度条）。
 */
export function parseRoundParams(
  key: string | undefined,
  params: Record<string, string | number> | undefined,
): RoundProgress | null {
  if (!key || !ROUND_STATUS_KEYS.has(key) || !params) return null;
  const step = Number(params.step);
  const max = Number(params.max);
  if (!Number.isFinite(step) || !Number.isFinite(max)) return null;
  if (step <= 0 || max <= 0) return null;
  return { step, max };
}

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

/** 轮次进度百分比（0-100，钳制；max 非法返回 0） */
export function roundPercent(round: RoundProgress | null): number {
  if (!round || round.max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((round.step / round.max) * 100)));
}
