/**
 * SSE 重连策略测试（任务 #30 传输层补强；按主题拆分并入）。
 *
 * 契约：网络/传输层瞬断 → 重连（后台任务仍在跑）；
 * 用户取消（AbortError）与任务面错误（4xx）→ 不重连。
 * 集成层：指数退避时序（500/1000ms）、重试耗尽归类、4xx 不重连、等待期归属变化。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('@/api/sse', () => ({
  startAgentTask: vi.fn(),
  fetchAgentTaskEvents: vi.fn(),
  stopAgentTask: vi.fn(),
  listAgentTasks: vi.fn(),
  postAgentTaskGuidance: vi.fn(),
}));
vi.mock('@/stores/history', () => ({ refreshHistoryStatus: vi.fn(async () => {}) }));
vi.mock('@/lib/chat/chat-input-bridge', () => ({ requestInsertMedia: vi.fn() }));
vi.mock('@/stores/toast', () => ({ showToast: vi.fn() }));

import { streamAgentChat, disconnectAgentStream, SseHttpError, isRetriableSubscribeError } from '../use-sse';
import { startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance } from '@/api/sse';
import { state } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { req, sseResponse, doneFrame, spies, clearSpies, resetChatTestState } from './use-sse-testkit';

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
});

beforeEach(() => {
  disconnectAgentStream();
  resetChatTestState();
  vi.mocked(startAgentTask).mockReset().mockResolvedValue({ task_id: 't1', project_id: 'p1' });
  vi.mocked(fetchAgentTaskEvents).mockReset();
  vi.mocked(stopAgentTask).mockReset().mockResolvedValue({ ok: true, cancelled: 1 });
  vi.mocked(listAgentTasks).mockReset().mockResolvedValue([]);
  vi.mocked(postAgentTaskGuidance).mockReset().mockResolvedValue({ ok: true });
  vi.mocked(showToast).mockClear();
  vi.mocked(requestInsertMedia).mockClear();
});

afterEach(() => {
  disconnectAgentStream();
  vi.useRealTimers();
  clearSpies();
});

describe('重连指数退避与订阅重试归类（集成）', () => {
  it('瞬断两次 → 500/1000ms 退避重订阅，第三次成功收尾', async () => {
    vi.useFakeTimers();
    const seq = [
      () => Promise.reject(new TypeError('Failed to fetch')),
      () => Promise.resolve(sseResponse([], 502)),
      () => Promise.resolve(sseResponse([doneFrame('重连后完成')])),
    ];
    vi.mocked(fetchAgentTaskEvents).mockImplementation(() => seq.shift()!());

    const p = streamAgentChat(req);
    await vi.advanceTimersByTimeAsync(0); // 首尝失败 → 排 500ms
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(1);
    expect(spies.setStatus).toHaveBeenCalledWith(expect.stringContaining('（1/3）'));

    await vi.advanceTimersByTimeAsync(499);
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(1); // 未到 500ms 不重连
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(2); // 第一档退避 = 500ms

    expect(spies.setStatus).toHaveBeenCalledWith(expect.stringContaining('（2/3）'));
    await vi.advanceTimersByTimeAsync(999);
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(2); // 未到 1000ms
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(3); // 第二档退避 = 1000ms

    await p;
    expect(spies.finishStream.mock.calls[0][0].text).toBe('重连后完成');
    expect(state.agentBusy).toBe(false);
  });

  it('重试耗尽（3 次退避后仍失败）：归类 network 落错误，不再重连', async () => {
    vi.useFakeTimers();
    vi.mocked(fetchAgentTaskEvents).mockRejectedValue(new TypeError('Failed to fetch'));

    const p = streamAgentChat(req);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(500);   // 退避 1
    await vi.advanceTimersByTimeAsync(1000);  // 退避 2
    await vi.advanceTimersByTimeAsync(2000);  // 退避 3
    await p;

    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(4); // 首尝 + 3 次重试
    expect(spies.streamError).toHaveBeenCalledTimes(1);
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({
      kind: 'network', code: 'err.network.connection',
    }));
    expect(state.agentBusy).toBe(false);
  });

  it('任务面 4xx（404 任务已清理）：不重连，按状态归类落错误', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([], 404));
    await streamAgentChat(req);
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(1); // 无重连
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({ kind: 'unknown' }));
  });

  it('重连等待期间归属变化（已切走）：放弃收尾不干扰新任务', async () => {
    vi.useFakeTimers();
    vi.mocked(fetchAgentTaskEvents).mockRejectedValue(new TypeError('Failed to fetch'));
    const p = streamAgentChat(req);
    await vi.advanceTimersByTimeAsync(0); // 首尝失败，退避等待中
    disconnectAgentStream();              // 模拟切项目断开（归属置空）
    await vi.advanceTimersByTimeAsync(500);
    await p;
    // 归属已变：不落错误、不走收尾清理（disconnect 已复位忙态）
    expect(spies.streamError).not.toHaveBeenCalled();
    expect(fetchAgentTaskEvents).toHaveBeenCalledTimes(1);
  });
});
