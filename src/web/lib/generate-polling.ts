/**
 * 生成任务等待：SSE 优先（按任务定向订阅 /api/generate/events/{task_id}），
 * SSE 失败/宽限期内无终态才启动轮询降级（指数退避）。完成后写回草稿 URL 并 toast。
 *
 * 任务7/P0：传输统一为 fetch + ReadableStream（原生 EventSource 无法携带
 * X-API-Key，生产模式必 401）；原「SSE 与轮询始终并行竞速」改为
 * 「SSE 优先 + 失败后降级轮询」，消除双通道重复请求浪费。
 */
import { studioActions } from '@/stores/studio';
import { findDraftRecord } from '@/stores/studio-core';
import { showToast } from '@/stores/toast';
import { getImageTaskStatus, getVideoTaskStatus } from '@/api/generate';
import { buildAuthHeaders } from '@/api/client';
import { pumpSseBody } from '@/lib/reconnecting-sse';
import type { DraftType, TaskResult } from '@/types';

export function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/** 草稿字段写回（通过 store action 保证响应式） */
export function patchDraft(draftId: string, type: DraftType, patch: Record<string, unknown>) {
  studioActions.updateDraftLocal(type, draftId, patch);
}

export function finishGeneration(draftId: string): string | null {
  const sec = studioActions.finishGeneration(draftId);
  return sec !== null ? sec.toFixed(1) : null;
}

const TERMINAL_STATUSES = new Set(['succeeded', 'completed', 'failed']);

/** SSE 宽限期（秒）：期内 SSE 未给出终态（失败/无事件）才启动轮询降级 */
export const SSE_GRACE_SEC = 5;
/** 降级轮询：首次间隔与指数退避封顶（3s → 6s → 12s → 15s 封顶） */
export const POLL_INITIAL_MS = 3000;
export const POLL_MAX_MS = 15000;

/** 指数退避：第 attempt（1 起）次轮询前的等待毫秒数 */
export function nextPollDelayMs(attempt: number): number {
  return Math.min(POLL_INITIAL_MS * 2 ** (attempt - 1), POLL_MAX_MS);
}

/**
 * 按任务定向 SSE 订阅等待终态；HTTP 失败/流中断/超时返回 null（调用方降级轮询）。
 * 后端在订阅时先回放终态快照再增量，连接晚于任务完成也不会漏事件。
 */
export function waitForTaskViaSSE(taskId: string, timeoutSec: number): Promise<TaskResult | null> {
  return new Promise((resolve) => {
    const controller = new AbortController();
    let settled = false;
    const finish = (r: TaskResult | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      controller.abort();
      resolve(r);
    };
    const timer = setTimeout(() => finish(null), timeoutSec * 1000);

    (async () => {
      try {
        const res = await fetch(
          `/api/generate/events/${encodeURIComponent(taskId)}`,
          { headers: buildAuthHeaders(), signal: controller.signal },
        );
        if (!res.ok || !res.body) { finish(null); return; }
        await pumpSseBody(res.body, (raw) => {
          try {
            const data = JSON.parse(raw) as TaskResult;
            if (data.task_id === taskId && TERMINAL_STATUSES.has(data.status)) {
              finish(data);
            }
          } catch { /* 忽略解析错误 */ }
        }, controller.signal);
      } catch { /* 网络中断/abort：统一降级 */ }
      finish(null);
    })();
  });
}

/**
 * SSE 优先 + 失败降级轮询（替代旧的始终并行竞速）：
 * 宽限期（SSE_GRACE_SEC）内 SSE 未给出终态才启动轮询，轮询间隔指数退避；
 * 两条通道任一拿到终态即终止另一条。总超时 timeoutSec 保底返回 null。
 */
export async function sseFirstThenPoll(
  taskId: string,
  pollFn: () => Promise<TaskResult>,
  timeoutSec: number,
): Promise<TaskResult | null> {
  return new Promise<TaskResult | null>((resolve) => {
    let settled = false;
    const done = (r: TaskResult | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(r);
    };
    // 总超时保底
    const timer = setTimeout(() => done(null), timeoutSec * 1000);
    let fallbackStarted = false;

    // 主通道：SSE（宽限期内无终态则先启动轮询兜底，但 SSE 不断连继续等）
    const startFallback = () => {
      if (!settled && !fallbackStarted) {
        fallbackStarted = true;
        void pollFallback();
      }
    };
    const grace = setTimeout(startFallback, SSE_GRACE_SEC * 1000);
    waitForTaskViaSSE(taskId, timeoutSec).then((r) => {
      if (r) { clearTimeout(grace); done(r); return; }
      // SSE 失败/超时：降级轮询立即启动（不等宽限期耗尽）
      clearTimeout(grace);
      startFallback();
    });

    // 降级通道：仅在 SSE 宽限期耗尽后启动，指数退避查询
    async function pollFallback(): Promise<void> {
      let attempt = 1;
      while (!settled) {
        await sleep(nextPollDelayMs(attempt));
        attempt += 1;
        if (settled) return;
        try {
          const data = await pollFn();
          if (TERMINAL_STATUSES.has(data.status)) { done(data); return; }
        } catch { /* 静默重试 */ }
      }
    }
  });
}

// ---------- 图片轮询 ----------

export async function pollAndPreviewImage(taskId: string, draftId: string): Promise<void> {
  const apply = (data: TaskResult) => {
    const t = findDraftRecord(draftId)?.type || 'keyElement';
    if (data.status === 'succeeded' && data.result?.images?.length) {
      patchDraft(draftId, t, {
        mediaType: 'image',
        genType: 'image',
        imgUrl: data.result.images[0],
        videoUrl: '',
        audioUrl: '',
        tag: '已生成',
      });
      const sec = data.elapsed || finishGeneration(draftId);
      finishGeneration(draftId);
      showToast(`图片渲染完成！耗时 ${sec}s`, 'success');
    } else if (data.status === 'failed') {
      patchDraft(draftId, t, { tag: '生成失败' });
      const sec = data.elapsed || finishGeneration(draftId);
      finishGeneration(draftId);
      showToast(`生成失败（${sec}s）: ${data.error || '未知错误'}`, 'error');
    }
  };

  const result = await sseFirstThenPoll(taskId, () => getImageTaskStatus(taskId), 300);
  if (result) { apply(result); return; }
  finishGeneration(draftId);
  showToast('生成超时（5 分钟），请检查供应商状态后重试', 'error');
}

// ---------- 视频轮询 ----------

export async function pollAndPreviewVideo(taskId: string, draftId: string): Promise<void> {
  const apply = (data: TaskResult) => {
    const t = findDraftRecord(draftId)?.type || 'shot';
    const url = data.video_url || data.result?.images?.[0];
    if ((data.status === 'succeeded' || data.status === 'completed') && url) {
      patchDraft(draftId, t, { mediaType: 'video', genType: 'video', videoUrl: url, imgUrl: '', audioUrl: '', tag: '已生成' });
      const sec = data.elapsed || finishGeneration(draftId);
      finishGeneration(draftId);
      showToast(`视频渲染完成！耗时 ${sec}s`, 'success');
    } else if (data.status === 'failed') {
      patchDraft(draftId, t, { tag: '生成失败' });
      const sec = data.elapsed || finishGeneration(draftId);
      finishGeneration(draftId);
      showToast(`视频生成失败（${sec}s）: ${data.error || '未知错误'}`, 'error');
    }
  };

  const result = await sseFirstThenPoll(taskId, () => getVideoTaskStatus(taskId), 600);
  if (result) { apply(result); return; }
  finishGeneration(draftId);
  showToast('视频生成超时（10 分钟），请检查供应商状态后重试', 'error');
}
