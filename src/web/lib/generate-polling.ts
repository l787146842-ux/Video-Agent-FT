/**
 * 生成任务等待：SSE 优先（/api/generate/events），降级 5s 轮询。
 * 完成后写回草稿 URL 并 toast 反馈。
 */
import { studioActions } from '@/stores/studio';
import { findDraftRecord } from '@/stores/studio-core';
import { showToast } from '@/stores/toast';
import { getImageTaskStatus, getVideoTaskStatus } from '@/api/generate';
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

/** SSE 等待任务完成；超时/失败返回 null（调用方降级轮询） */
export function waitForTaskViaSSE(taskId: string, timeoutSec: number): Promise<TaskResult | null> {
  return new Promise((resolve) => {
    let resolved = false;
    const timer = setTimeout(() => { cleanup(); resolve(null); }, timeoutSec * 1000);

    let es: EventSource | null = null;
    try {
      es = new EventSource('/api/generate/events');
    } catch {
      clearTimeout(timer);
      resolve(null);
      return;
    }

    function cleanup() {
      if (es) { es.close(); es = null; }
      clearTimeout(timer);
    }

    es.onmessage = (event: MessageEvent) => {
      if (resolved) return;
      try {
        const data = JSON.parse(event.data) as TaskResult & { task_id?: string };
        if (data.task_id === taskId) {
          resolved = true;
          cleanup();
          resolve(data);
        }
      } catch { /* 忽略解析错误 */ }
    };
    es.onerror = () => {
      if (!resolved) {
        resolved = true;
        cleanup();
        resolve(null);
      }
    };
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
        tag: data.mock ? 'mock 演示' : '已生成',
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

  // SSE 和轮询并行竞速，谁先拿到结果用谁
  const result = await raceSSEAndPoll(taskId, () => getImageTaskStatus(taskId), 300);
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
      patchDraft(draftId, t, { mediaType: 'video', genType: 'video', videoUrl: url, imgUrl: '', audioUrl: '', tag: data.mock ? 'mock 演示' : '已生成' });
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

  // SSE 和轮询并行竞速
  const result = await raceSSEAndPoll(taskId, () => getVideoTaskStatus(taskId), 600);
  if (result) { apply(result); return; }
  finishGeneration(draftId);
  showToast('视频生成超时（10 分钟），请检查供应商状态后重试', 'error');
}

// ---------- SSE + 轮询并行竞速 ----------

/**
 * SSE 和轮询并行执行，谁先拿到非 null 终态结果用谁。
 * 解决 SSE 事件在连接建立前已发出导致前端傻等的问题。
 */
async function raceSSEAndPoll(
  taskId: string,
  pollFn: () => Promise<TaskResult>,
  timeoutSec: number,
): Promise<TaskResult | null> {
  return new Promise<TaskResult | null>((resolve) => {
    let settled = false;
    const done = (r: TaskResult | null) => {
      if (!settled) { settled = true; resolve(r); }
    };

    // 总超时保底
    const timer = setTimeout(() => done(null), timeoutSec * 1000);

    // SSE 通道
    waitForTaskViaSSE(taskId, timeoutSec).then((r) => {
      if (r) done(r);
    });

    // 轮询通道（每 3 秒查一次，首次延迟 2 秒）
    (async () => {
      await sleep(2000);
      const maxAttempts = Math.ceil((timeoutSec * 1000) / 3000);
      for (let i = 0; i < maxAttempts; i++) {
        if (settled) return;
        try {
          const data = await pollFn();
          if (data.status === 'succeeded' || data.status === 'completed' || data.status === 'failed') {
            clearTimeout(timer);
            done(data);
            return;
          }
        } catch { /* 静默重试 */ }
        await sleep(3000);
      }
    })();
  });
}
