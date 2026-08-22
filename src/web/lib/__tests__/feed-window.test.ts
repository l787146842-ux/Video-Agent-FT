/**
 * 长会话消息窗口化派生测试：
 * ① computeFeedStart——窗口钉尾，未超基底全量渲染；
 * ② expandFeedWindow——向前展开一批；
 * ③ extraForIndex——跳转所需最小展开量（窗口内为 0）。
 */
import { describe, it, expect } from 'vitest';
import {
  FEED_WINDOW_BASE, FEED_WINDOW_BATCH,
  computeFeedStart, expandFeedWindow, extraForIndex,
} from '@/lib/feed-window';

describe('computeFeedStart 窗口起点', () => {
  it('消息数不超过基底时全量渲染（起点 0）', () => {
    expect(computeFeedStart(0, 0)).toBe(0);
    expect(computeFeedStart(FEED_WINDOW_BASE, 0)).toBe(0);
  });

  it('超出基底时只裁头部，起点 = 总数 - 基底', () => {
    expect(computeFeedStart(FEED_WINDOW_BASE + 30, 0)).toBe(30);
  });

  it('已展开量抵扣裁剪，展开到位后回到全量（不减到负数）', () => {
    expect(computeFeedStart(FEED_WINDOW_BASE + 30, 30)).toBe(0);
    expect(computeFeedStart(FEED_WINDOW_BASE + 30, 999)).toBe(0);
    expect(computeFeedStart(FEED_WINDOW_BASE + 30, -5)).toBe(30);
  });
});

describe('expandFeedWindow 向前展开', () => {
  it('每点一次累加一批', () => {
    expect(expandFeedWindow(0)).toBe(FEED_WINDOW_BATCH);
    expect(expandFeedWindow(FEED_WINDOW_BATCH)).toBe(FEED_WINDOW_BATCH * 2);
  });

  it('负数起点视为 0（防御异常状态）', () => {
    expect(expandFeedWindow(-10)).toBe(FEED_WINDOW_BATCH);
  });
});

describe('extraForIndex 跳转扩窗量', () => {
  it('目标已在基底窗口内 → 不需要展开', () => {
    expect(extraForIndex(FEED_WINDOW_BASE, FEED_WINDOW_BASE + 50)).toBe(0);
    expect(extraForIndex(FEED_WINDOW_BASE + 49, FEED_WINDOW_BASE + 50)).toBe(0);
  });

  it('目标在折叠头部 → 展开到恰好纳入（extra = total - base - index）', () => {
    expect(extraForIndex(0, FEED_WINDOW_BASE + 50)).toBe(50);
    expect(extraForIndex(10, FEED_WINDOW_BASE + 50)).toBe(40);
  });
});
