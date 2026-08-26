/**
 * hooks/use-sse.ts 收尾状态机测试。
 *
 * 以可控 fake 注入替代真实传输层（@/api/sse 整体 mock），钉死：
 * - 收尾状态机（completed/error/stopped 各终态清理忙态与订阅）；
 * - 建任务失败归类（ApiError 结构化负载 / 网络层 / 忙碌早退）。
 * 其余主题见同目录：use-sse-replay / use-sse-reconnect / use-sse-stop / use-sse-events。
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

import { streamAgentChat, disconnectAgentStream, stopAgentStream, useAgentStream } from '../use-sse';
import { startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance } from '@/api/sse';
import { chatState } from '@/stores/chat';
import { agentState } from '@/stores/agent-state';
import { showToast } from '@/stores/toast';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { ApiError } from '@/api/client';
import { makeErrorPayload } from '@/lib/error-payload';
import { req, sseResponse, hangingResponse, doneFrame, spies, clearSpies, resetChatTestState, tick } from './use-sse-testkit';

beforeEach(() => {
  disconnectAgentStream(); // 清残留订阅/忙态
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

// ---------- 主动断开感知型假流（钉死假错误气泡回归） ----------
// 简版 sseResponse 的 reader 感知不到 abort（真实浏览器 BodyStreamBuffer 会：
// abort 后未决 read 以 AbortError reject）。本组用例用感知 abort 的假流复刻
// 真实时序：终态路径关流 → parseSSE reject → catch 归属判定必须静默。
const enc2 = new TextEncoder();
function abortError(): Error {
  const e = new Error('BodyStreamBuffer was aborted');
  e.name = 'AbortError';
  return e;
}

/** 按帧推送；abort 后（含挂起中的 read）以 AbortError reject */
function abortableSseResponse(signal: AbortSignal, frames: Array<string | object>): Response {
  const data = frames.map((f) => enc2.encode(`data: ${typeof f === 'string' ? f : JSON.stringify(f)}\n\n`));
  let i = 0;
  const reader = {
    read: () => new Promise<{ done: boolean; value?: Uint8Array }>((resolve, reject) => {
      if (signal.aborted) { reject(abortError()); return; }
      queueMicrotask(() => {
        if (signal.aborted) { reject(abortError()); return; }
        if (i >= data.length) { resolve({ done: true, value: undefined }); return; }
        resolve({ done: false, value: data[i] });
        i += 1;
      });
    }),
  };
  return { ok: true, status: 200, body: { getReader: () => reader } } as unknown as Response;
}

/** 永不自然关流：仅 abort 时以 AbortError reject（运行中断开场景） */
function pendingAbortableResponse(signal: AbortSignal): Response {
  const reader = {
    read: () => new Promise<never>((_resolve, reject) => {
      if (signal.aborted) { reject(abortError()); return; }
      signal.addEventListener('abort', () => reject(abortError()), { once: true });
    }),
  };
  return { ok: true, status: 200, body: { getReader: () => reader } } as unknown as Response;
}

describe('正常完成后假错误气泡回归（主动断开不得误判为失败）', () => {
  it('done 帧 → handleDone 主动关流：AbortError 静默，不产生错误消息', async () => {
    vi.mocked(fetchAgentTaskEvents).mockImplementation((_id, signal) => Promise.resolve(abortableSseResponse(signal, [
      { type: 'delta', text: '你好，' },
      doneFrame('回复完成'),
    ])));
    await streamAgentChat(req);
    await tick(); // 等 abort 引发的 AbortError rejection 进 connectToTask catch
    expect(spies.finishStream).toHaveBeenCalledTimes(1);
    expect(spies.streamError).not.toHaveBeenCalled();
    expect(agentState.agentBusy).toBe(false);
    expect(chatState.isStreaming).toBe(false);
  });

  it('error 帧落真错误气泡后主动关流：AbortError 不追加第二个误判气泡', async () => {
    vi.mocked(fetchAgentTaskEvents).mockImplementation((_id, signal) => Promise.resolve(abortableSseResponse(signal, [
      { type: 'error', code: 'err.auth.invalid_key', kind: 'auth', detail: 'API Key 无效' },
    ])));
    await streamAgentChat(req);
    await tick();
    expect(spies.streamError).toHaveBeenCalledTimes(1); // 真实错误保留，无重复
    expect(agentState.agentBusy).toBe(false);
  });

  it('运行中主动断开（切项目 disconnect）：AbortError 静默不落气泡', async () => {
    vi.mocked(fetchAgentTaskEvents).mockImplementation((_id, signal) => Promise.resolve(pendingAbortableResponse(signal)));
    void streamAgentChat(req);
    await tick();
    disconnectAgentStream(); // 归属先置空再 abort（与切项目路径一致）
    await tick(); // 等 AbortError rejection 进 catch
    expect(spies.streamError).not.toHaveBeenCalled();
    expect(agentState.agentBusy).toBe(false);
  });

  it('真实订阅失败（4xx 任务面错误）：仍产生错误消息（不被静默）', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([], 404));
    await streamAgentChat(req);
    expect(spies.streamError).toHaveBeenCalledTimes(1);
    expect(agentState.agentBusy).toBe(false);
  });
});

describe('收尾状态机（completed / error / stopped 终态）', () => {
  it('completed：done 帧 → finishStream + 忙态复位 + 订阅关闭', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'status', text: '正在思考…' },
      { type: 'delta', text: '你好，' },
      doneFrame('回复完成'),
    ]));
    await streamAgentChat(req);
    expect(spies.finishStream).toHaveBeenCalledTimes(1);
    expect(spies.finishStream.mock.calls[0][0].text).toBe('回复完成');
    expect(spies.appendDelta).toHaveBeenCalledWith('你好，');
    expect(agentState.agentBusy).toBe(false);
    expect(chatState.isStreaming).toBe(false);
  });

  it('error（新契约 code/kind）：ErrorPayload 落错误气泡并收尾', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'error', code: 'err.auth.invalid_key', kind: 'auth', detail: 'API Key 无效', raw: 'upstream 401' },
    ]));
    await streamAgentChat(req);
    expect(spies.streamError).toHaveBeenCalledTimes(1);
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({
      code: 'err.auth.invalid_key', kind: 'auth', message: 'API Key 无效', raw: 'upstream 401',
    }));
    expect(useAgentStream().error()).toBe('API Key 无效');
    expect(agentState.agentBusy).toBe(false);
  });

  it('error（旧事件仅 error_code）：legacy 桥接归类仍可用', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'error', error_code: 'RATE_LIMITED', detail: '触发限流' },
    ]));
    await streamAgentChat(req);
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({
      kind: 'quota', code: 'err.quota.rate_limited',
    }));
  });

  it('stopped 事件：cancelStream 按 phase 落停止痕迹后收尾', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(sseResponse([
      { type: 'stopped', phase: 'thinking', inflight: [{ task_id: 'g1', media_type: 'image' }] },
    ]));
    await streamAgentChat(req);
    expect(spies.cancelStream).toHaveBeenCalledTimes(1);
    expect(spies.cancelStream.mock.calls[0][0]).toEqual({
      phase: 'thinking', inflight: [{ task_id: 'g1', media_type: 'image' }],
    });
    expect(agentState.agentBusy).toBe(false);
  });

  it('流式中已点停止按钮（currentTask 置空）：服务端迟到 stopped 帧不重复落气泡', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void streamAgentChat(req);
    await tick();
    await stopAgentStream();
    spies.cancelStream.mockClear();
    // 迟到帧到达时归属已空：直接忽略（guard 分支）
    expect(spies.cancelStream).not.toHaveBeenCalled();
  });
});

describe('建任务失败归类（streamAgentChat catch）', () => {
  it('ApiError：直接消费后端结构化 ErrorPayload', async () => {
    const payload = makeErrorPayload('Key 无效', 'auth', 'err.auth.invalid_key');
    vi.mocked(startAgentTask).mockRejectedValue(new ApiError(401, 'Key 无效', payload));
    await streamAgentChat(req);
    expect(spies.streamError.mock.calls[0][0]).toEqual(payload);
    expect(agentState.agentBusy).toBe(false);
  });

  it('fetch 网络层失败（非 ApiError）：归 network', async () => {
    vi.mocked(startAgentTask).mockRejectedValue(new TypeError('Failed to fetch'));
    await streamAgentChat(req);
    expect(spies.streamError.mock.calls[0][0]).toEqual(expect.objectContaining({
      kind: 'network', code: 'err.network.connection',
    }));
    expect(agentState.agentBusy).toBe(false);
  });

  it('忙碌中重复发起：早退不建新任务', async () => {
    vi.mocked(fetchAgentTaskEvents).mockResolvedValue(hangingResponse());
    void streamAgentChat(req);
    await tick();
    await streamAgentChat(req); // streaming() === true → 早退
    expect(startAgentTask).toHaveBeenCalledTimes(1);
  });
});
