/**
 * 长会话消息窗口化（只渲染近段，向前按需展开）。
 *
 * 全部消息节点常驻 DOM 的成本随会话长度线性增长；此处把渲染窗口钉在
 * 消息尾部：近段 base 条常驻，用户点「显示更早的消息」每次向前扩一批。
 * 窗口只裁头部，底部钉底跟随逻辑不受影响；DOM 节点数封顶 =
 * base + 已展开批次，长会话内存与重建成本不再线性增长。
 */

/** 常驻近段条数（窗口基底） */
export const FEED_WINDOW_BASE = 120;
/** 每次「显示更早的消息」向前展开的条数 */
export const FEED_WINDOW_BATCH = 120;

/**
 * 计算渲染窗口起点下标：total 不超过 base+extra 时全量渲染（返回 0）。
 * extra = 用户已展开的累计条数（0 = 仅基底）。
 */
export function computeFeedStart(
  total: number, extra: number, base: number = FEED_WINDOW_BASE,
): number {
  if (total <= 0) return 0;
  return Math.max(0, total - base - Math.max(0, extra));
}

/** 展开一批后应设置的新 extra 值（不减到负数） */
export function expandFeedWindow(currentExtra: number, batch: number = FEED_WINDOW_BATCH): number {
  return Math.max(0, currentExtra) + batch;
}

/** 跳转到指定下标所需的最小 extra（目标已在窗口内返回 0） */
export function extraForIndex(
  index: number, total: number, base: number = FEED_WINDOW_BASE,
): number {
  const start = computeFeedStart(total, 0, base);
  if (index >= start) return 0;
  return total - base - index;
}
