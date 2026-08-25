/**
 * lib/sse-connection 纯函数单测（任务 #18：use-sse.ts 连接状态机瘦身）。
 *
 * 钉死：终态清理顺序（先复位忙态、置空归属，再关订阅——顺序搞反曾产生
 * 假错误气泡）、指数退避调度（3 次、500ms 基数）、归属判定、重连判定、
 * 排队/不打断的轮间注入判定。纯函数无 I/O，无需 mock 任何 store。
 */
import { describe, it, expect, vi } from 'vitest';
import {
  SseHttpError, isRetriableSubscribeError, reconnectDelayMs, ownsTask, shouldQueueGuidance,
  finalizeTerminal, MAX_RECONNECT_ATTEMPTS, RECONNECT_BASE_DELAY_MS, type TaskRef,
} from '../sse-connection';

describe('finalizeTerminal（终态清理顺序——历史坑显式钉死）', () => {
  it('严格顺序：复位忙态 → 置空归属 → 关订阅', () => {
    const calls: string[] = [];
    finalizeTerminal({
      resetBusy: () => calls.push('resetBusy'),
      clearOwnership: () => calls.push('clearOwnership'),
      closeSubscription: () => calls.push('closeSubscription'),
    });
    expect(calls).toEqual(['resetBusy', 'clearOwnership', 'closeSubscription']);
  });

  it('关订阅必须最后执行（提前 abort 会使归属判定把主动断开误判为失败）', () => {
    const resetBusy = vi.fn();
    const clearOwnership = vi.fn();
    const closeSubscription = vi.fn();
    finalizeTerminal({ resetBusy, clearOwnership, closeSubscription });
    expect(resetBusy).toHaveBeenCalledTimes(1);
    expect(clearOwnership).toHaveBeenCalledTimes(1);
    expect(closeSubscription).toHaveBeenCalledTimes(1);
    const closeOrder = closeSubscription.mock.invocationCallOrder[0];
    expect(closeOrder).toBeGreaterThan(resetBusy.mock.invocationCallOrder[0]);
    expect(closeOrder).toBeGreaterThan(clearOwnership.mock.invocationCallOrder[0]);
  });
});

describe('reconnectDelayMs（指数退避调度：3 次、500ms 基数）', () => {
  it('第 1/2/3 次重试分别等待 500/1000/2000ms', () => {
    expect(reconnectDelayMs(1)).toBe(500);
    expect(reconnectDelayMs(2)).toBe(1000);
    expect(reconnectDelayMs(3)).toBe(2000);
  });

  it('基数常量与重试上限契约', () => {
    expect(RECONNECT_BASE_DELAY_MS).toBe(500);
    expect(MAX_RECONNECT_ATTEMPTS).toBe(3);
    expect(reconnectDelayMs(1, 100)).toBe(100);
    expect(reconnectDelayMs(3, 100)).toBe(400);
  });
});

describe('ownsTask（任务归属判定）', () => {
  it('归属匹配 / 换任务 / 已置空', () => {
    expect(ownsTask({ taskId: 't1' }, 't1')).toBe(true);
    expect(ownsTask({ taskId: 't1' }, 't2')).toBe(false);
    expect(ownsTask(null, 't1')).toBe(false);
    expect(ownsTask(undefined, 't1')).toBe(false);
  });
});

describe('shouldQueueGuidance（排队/不打断的轮间注入判定）', () => {
  const task: TaskRef = { taskId: 't1', projectId: 'p1', recovering: false };

  it('有运行中任务且文本非空才登记', () => {
    expect(shouldQueueGuidance(task, '加个彩蛋')).toBe(true);
  });

  it('无活动任务 / 空白文本：不登记（回落自动出队路径）', () => {
    expect(shouldQueueGuidance(null, '加个彩蛋')).toBe(false);
    expect(shouldQueueGuidance(task, '')).toBe(false);
    expect(shouldQueueGuidance(task, '   ')).toBe(false);
  });
});

describe('isRetriableSubscribeError（重连判定）', () => {
  it('用户取消（AbortError）不重连', () => {
    const err = new Error('aborted');
    err.name = 'AbortError';
    expect(isRetriableSubscribeError(err)).toBe(false);
  });

  it('任务面 4xx 错误不重连（任务不存在/已清理）', () => {
    expect(isRetriableSubscribeError(new SseHttpError(404))).toBe(false);
    expect(isRetriableSubscribeError(new SseHttpError(410))).toBe(false);
  });

  it('瞬态 HTTP 状态重连（408/429/5xx）', () => {
    expect(isRetriableSubscribeError(new SseHttpError(408))).toBe(true);
    expect(isRetriableSubscribeError(new SseHttpError(429))).toBe(true);
    expect(isRetriableSubscribeError(new SseHttpError(502))).toBe(true);
  });

  it('fetch 网络错误/读流中断重连（后台任务仍在跑）', () => {
    expect(isRetriableSubscribeError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isRetriableSubscribeError(new Error('network read interrupted'))).toBe(true);
  });

  it('SseHttpError 携带 status 与语义化消息', () => {
    const err = new SseHttpError(404);
    expect(err.status).toBe(404);
    expect(err.name).toBe('SseHttpError');
    expect(err.message).toContain('404');
  });
});
