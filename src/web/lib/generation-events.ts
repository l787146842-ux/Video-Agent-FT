/**
 * 全局生成事件总线 — 订阅 /api/generate/events（自动重连）。
 *
 * 作用：
 * 1. Agent/批量触发的生成任务（前端未主动提交）也能驱动 UI：
 *    started → 卡片/预览框点亮转圈读秒；succeeded/failed → 写回草稿并结束计时（改进2）。
 * 2. 每条事件刷新「生成日志」面板数据与未读角标（改进3）。
 *
 * 去重：手动路径（generate-actions.ts）提交的任务会 registerManualTask，
 * 其结果处理由各自的 pollAndPreview* 负责，本总线跳过避免重复写回/toast。
 */
import { createReconnectingSSE } from './reconnecting-sse';
import { state, studioActions } from '@/stores/studio';
import { findDraftRecord } from '@/stores/studio-core';
import { genLogs, refreshGenLogs, bumpGenLogUnread } from '@/stores/generation-log';
import { getActiveGenTasks } from '@/api/generate';
import type { Draft } from '@/types';

interface GenerateEvent {
  task_id?: string;
  status?: string;
  kind?: string;
  draft_id?: string;
  result?: { images?: string[] };
  video_url?: string;
  error?: string;
  elapsed?: number;
}

/** 手动路径提交的任务 id（全局总线跳过，避免与其轮询/SSE 重复处理） */
const manualTaskIds = new Set<string>();

/** 手动路径提交任务后登记（15 分钟后自动释放，防集合无限增长） */
export function registerManualTask(taskId: string): void {
  manualTaskIds.add(taskId);
  setTimeout(() => manualTaskIds.delete(taskId), 15 * 60 * 1000);
}

let initialized = false;

let pruning = false;

/**
 * 本地读秒与后端权威任务对账：后端已无 processing 任务的草稿，
 * 立即停止其本地读秒。兜底 SSE 终态事件丢失（断线重连窗口/队列溢出）
 * 导致「生成失败后仍一直读秒、刷新才消失」的问题。
 * 同时按最新生成日志把卡在「生成中」的标签纠正为「生成失败」。
 */
export async function pruneStaleGenerations(): Promise<void> {
  if (pruning) return;
  const ids = Object.keys(state.activeGenerations || {});
  if (!ids.length) return;
  pruning = true;
  try {
    const data = await getActiveGenTasks();
    const activeDrafts = new Set(
      (data.tasks || []).map((t) => t.draft_id).filter(Boolean),
    );
    for (const draftId of ids) {
      if (activeDrafts.has(draftId)) continue;
      studioActions.finishGeneration(draftId);
      // 终态事件丢失时卡片可能仍标「生成中」：按最新一条生成日志纠正
      const rec = findDraftRecord(draftId);
      const latest = genLogs().find((l) => l.draft_id === draftId);
      if (rec && latest?.status === 'failed' && rec.draft.tag !== '生成失败') {
        studioActions.updateDraftLocal(rec.type, draftId, { tag: '生成失败' });
      }
    }
  } catch { /* 后端未就绪静默降级 */ } finally {
    pruning = false;
  }
}

/**
 * 刷新页面后恢复读秒：activeGenerations 仅存于前端内存，刷新即丢；
 * 从后端查询仍在处理中的任务，按任务创建时间回填已耗时，
 * 重新点亮卡片/预览框转圈（后续 SSE 事件到达时正常收尾）。
 */
export async function restoreActiveGenerations(): Promise<void> {
  try {
    const data = await getActiveGenTasks();
    for (const t of data.tasks || []) {
      if (!t.draft_id || !findDraftRecord(t.draft_id)) continue;
      const startedAt = t.created_at > 0 ? t.created_at * 1000 : Date.now();
      studioActions.startGeneration(t.draft_id, t.kind === 'video' ? 'video' : 'image', startedAt);
    }
  } catch { /* 后端未就绪静默降级 */ }
}

/** 应用启动时调用一次（LayoutShell onMount） */
export function initGenerationEvents(): void {
  if (initialized) return;
  initialized = true;

  createReconnectingSSE('/api/generate/events', (raw: string) => {
    if (!raw || raw.startsWith(':')) return; // 心跳
    let ev: GenerateEvent;
    try {
      ev = JSON.parse(raw) as GenerateEvent;
    } catch {
      return;
    }

    // 生成日志联动：新事件 → 未读角标 + 静默刷新（面板打开时即时可见）
    if (ev.status) {
      bumpGenLogUnread();
      void refreshGenLogs();
      // 每个事件后对账一次，及时停掉后端已无 processing 任务的读秒
      void pruneStaleGenerations();
    }

    const taskId = ev.task_id || '';
    const draftId = ev.draft_id || '';
    if (!draftId || !ev.status) return;
    if (manualTaskIds.has(taskId)) return; // 手动路径自行处理

    const rec = findDraftRecord(draftId);
    if (!rec) return;
    const kind: 'image' | 'video' = ev.kind === 'video' ? 'video' : 'image';

    if (ev.status === 'started') {
      // 卡片 + 中间预览框立即进入「生成中」转圈读秒状态
      studioActions.startGeneration(draftId, kind);
      studioActions.updateDraftLocal(rec.type, draftId, { tag: '生成中', genType: kind });
    } else if (ev.status === 'succeeded') {
      const url = ev.result?.images?.[0] || ev.video_url || '';
      if (url) {
        const patch: Partial<Draft> = kind === 'video'
          ? { mediaType: 'video', genType: 'video', videoUrl: url, imgUrl: '', audioUrl: '', tag: '已生成' }
          : { mediaType: 'image', genType: 'image', imgUrl: url, videoUrl: '', audioUrl: '', tag: '已生成' };
        studioActions.updateDraftLocal(rec.type, draftId, patch);
      }
      studioActions.finishGeneration(draftId);
    } else if (ev.status === 'failed') {
      studioActions.updateDraftLocal(rec.type, draftId, { tag: '生成失败' });
      studioActions.finishGeneration(draftId);
    }
  });

  // 周期对账兜底：SSE 终态事件彻底丢失时（无任何新事件触发），
  // 最多 15s 内也能停掉失败后的残留读秒
  setInterval(() => { void pruneStaleGenerations(); }, 15000);
}
