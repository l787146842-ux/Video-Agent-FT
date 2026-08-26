/**
 * generate-polling 传输与竞速策略测试（任务7/P0）。
 * 钉死：按任务定向 SSE 订阅携带 X-API-Key（生产鉴权闭环）、
 * 终态帧解析、HTTP 失败降级、SSE 优先 + 失败/宽限期后指数退避轮询降级。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  waitForTaskViaSSE, sseFirstThenPoll, nextPollDelayMs,
  SSE_GRACE_SEC, POLL_INITIAL_MS, POLL_MAX_MS,
} from '../generate-polling';
import { setGlobalApiKey } from '@/api/client';

const fetchMock = vi.fn();

/** 按帧推送后自然关流的 SSE 响应假件 */
function sseResponse(frames: string[], status = 200): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(enc.encode(f));
      controller.close();
    },
  });
  return { ok: status >= 200 && status < 300, status, body } as unknown as Response;
}

/** 永不关流的响应（SSE 保持等待用） */
function openStreamResponse(): Response {
  const body = new ReadableStream<Uint8Array>({ start() { /* 不 close */ } });
  return { ok: true, status: 200, body } as unknown as Response;
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('waitForTaskViaSSE（按任务定向订阅）', () => {
  it('订阅 URL 编码 taskId；携带 X-API-Key（生产模式鉴权头断言）', async () => {
    setGlobalApiKey('sk-prod-789');
    fetchMock.mockImplementation(async () => openStreamResponse());
    const p = waitForTaskViaSSE('img/任务 1', 10);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/generate/events/img%2F%E4%BB%BB%E5%8A%A1%201');
    expect(init.headers['X-API-Key']).toBe('sk-prod-789');
    // 不等终态帧：超时参数给小，让 promise 自行了结（避免悬挂）
    const r = await Promise.race([p, new Promise((res) => setTimeout(() => res('pending'), 50))]);
    expect(r === 'pending' || r === null).toBe(true);
  });

  it('未配置 Key 时不注入 X-API-Key（开发模式无害）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 200));
    await waitForTaskViaSSE('t1', 10);
    expect(fetchMock.mock.calls[0][1].headers['X-API-Key']).toBeUndefined();
  });

  it('收到本任务终态帧即解析返回（started 等非终态帧忽略）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([
      `data: ${JSON.stringify({ task_id: 't1', status: 'started' })}\n\n`,
      `data: ${JSON.stringify({ task_id: 't1', status: 'succeeded', result: { images: ['u1'] }, elapsed: 3.2 })}\n\n`,
    ]));
    const r = await waitForTaskViaSSE('t1', 10);
    expect(r).toMatchObject({ task_id: 't1', status: 'succeeded' });
    expect(r?.result?.images?.[0]).toBe('u1');
  });

  it('HTTP 失败（如生产 401）返回 null → 由调用方降级轮询', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 401));
    await expect(waitForTaskViaSSE('t1', 10)).resolves.toBeNull();
  });

  it('流正常关闭但无终态帧 → 返回 null（晚到订阅由轮询兜底）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([
      `data: ${JSON.stringify({ task_id: 't1', status: 'started' })}\n\n`,
    ]));
    await expect(waitForTaskViaSSE('t1', 10)).resolves.toBeNull();
  });
});

describe('sseFirstThenPoll（SSE 优先 + 失败后指数退避降级）', () => {
  it('SSE 直接给出终态 → 轮询一次不发起（删除始终并行竞速）', async () => {
    fetchMock.mockImplementation(async () => sseResponse([
      `data: ${JSON.stringify({ task_id: 't1', status: 'succeeded', elapsed: 1 })}\n\n`,
    ]));
    const pollFn = vi.fn();
    vi.useFakeTimers();
    const r = await sseFirstThenPoll('t1', pollFn, 300);
    expect(r).toMatchObject({ status: 'succeeded' });
    await vi.advanceTimersByTimeAsync((SSE_GRACE_SEC + 60) * 1000);
    expect(pollFn).not.toHaveBeenCalled();
  });

  it('SSE 失败 → 降级轮询立即启动（首次 3s），命中终态即返回', async () => {
    fetchMock.mockImplementation(async () => sseResponse([], 500));
    const pollFn = vi.fn()
      .mockResolvedValueOnce({ status: 'processing' } as never)
      .mockResolvedValueOnce({ status: 'succeeded', elapsed: 9 } as never);
    vi.useFakeTimers();
    const p = sseFirstThenPoll('t1', pollFn, 300);
    await vi.advanceTimersByTimeAsync(0); // SSE 失败落定 → 降级通道已启动
    expect(pollFn).not.toHaveBeenCalled(); // 首次查询前先等 3s 间隔

    await vi.advanceTimersByTimeAsync(POLL_INITIAL_MS - 1);
    expect(pollFn).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1); // 首次轮询（3s）
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(POLL_INITIAL_MS * 2); // 退避翻倍 6s 后第二次
    await expect(p).resolves.toMatchObject({ status: 'succeeded' });
    expect(pollFn).toHaveBeenCalledTimes(2);
  });

  it('宽限期内 SSE 无终态 → 启动轮询兜底，SSE 迟到终态仍优先生效', async () => {
    // SSE 流保持打开不出帧；轮询始终 processing → 最终靠总超时不测，只测启动
    fetchMock.mockImplementation(async () => openStreamResponse());
    const pollFn = vi.fn().mockResolvedValue({ status: 'processing' } as never);
    vi.useFakeTimers();
    void sseFirstThenPoll('t1', pollFn, 300);
    await vi.advanceTimersByTimeAsync((SSE_GRACE_SEC - 1) * 1000);
    expect(pollFn).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000 + POLL_INITIAL_MS);
    expect(pollFn).toHaveBeenCalledTimes(1);
  });

  it('轮询间隔指数退避并封顶（3s → 6s → 12s → 15s）', () => {
    expect(nextPollDelayMs(1)).toBe(POLL_INITIAL_MS);
    expect(nextPollDelayMs(2)).toBe(POLL_INITIAL_MS * 2);
    expect(nextPollDelayMs(3)).toBe(POLL_INITIAL_MS * 4);
    expect(nextPollDelayMs(4)).toBe(POLL_MAX_MS);
    expect(nextPollDelayMs(10)).toBe(POLL_MAX_MS);
  });
});
