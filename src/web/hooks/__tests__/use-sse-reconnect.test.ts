/**
 * SSE 重连策略测试（批1 验收补测：断线重连判定钉死）。
 *
 * 契约：网络/传输层瞬断 → 重连（后台任务仍在跑）；
 * 用户取消（AbortError）与任务面错误（4xx）→ 不重连。
 */
import { describe, it, expect } from 'vitest';
import { SseHttpError, isRetriableSubscribeError } from '../use-sse';

describe('isRetriableSubscribeError（批1 重连判定）', () => {
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
});
