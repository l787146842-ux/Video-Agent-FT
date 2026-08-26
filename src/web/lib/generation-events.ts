/**
 * 全局生成事件总线 — 订阅 /api/generate/events（fetch 传输 + 自动重连）。
 *
 * 任务7/P0：传输由 EventSource 切换为 createReconnectingSSE 的
 * fetch + ReadableStream（携带 X-API-Key），生产模式不再 401。
 *
 * 作用：
 * 1. Agent/批量触发的生成任务（前端未主动提交）也能驱动 UI：
 *    started → 卡片/预览框点亮转圈读秒；succeeded/failed → 写回草稿并结束计时（改进2）。
 * 2. 每条事件刷新「生成日志」面板数据与未读角标（改进3）。
 *
 * 去重：手动路径（generate-actions.ts）提交的任务会 registerManualTask，
 * 其结果处理由各自的 pollAndPreview* 负责，本总线跳过避免重复写回/toast；
 * 终态帧到达时事件驱动主动释放（TTL 仅作兜底）。
 * 帧级去重：消费后端 event_seq（每 task_id 单调递增，随 notify 帧下发，
 * replay/终态快照帧带原始 seq），防重连窗口 replay 与增量同源双达；
 * 无该字段的帧兼容跳过不去重。
 */
import { createReconnectingSSE } from './reconnecting-sse';
import { state, studioActions } from '@/stores/studio';
import { findDraftRecord } from '@/stores/studio-core';
import { genLogs, refreshGenLogs, bumpGenLogUnread } from '@/stores/generation-log';
import { getActiveGenTasks } from '@/api/generate';
import type { Draft } from '@/types';

interface GenerateEvent {
  task_id?: string;
  /** 契约：每 task_id 单调递增整数，随 notify 帧下发；replay/终态快照帧带原始 seq；旧帧可缺省 */
  event_seq?: number;
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

/** 手动任务登记 TTL 兜底：对齐视频任务 30 分钟上限留 5 分钟余量；
 * 正常由终态帧事件驱动释放，不依赖到期 */
const MANUAL_TASK_TTL_MS = 35 * 60 * 1000;

/** 手动路径提交任务后登记（终态帧到达事件驱动释放；TTL 仅兜底防集合无限增长） */
export function registerManualTask(taskId: string): void {
  manualTaskIds.add(taskId);
  setTimeout(() => manualTaskIds.delete(taskId), MANUAL_TASK_TTL_MS);
}

// ===== event_seq 帧级去重（无该字段的帧兼容跳过不去重） =====
const EVENT_SEQ_SEEN_LIMIT = 500;
const seenEventKeys = new Set<string>();
const seqBaselineByTask = new Map<string, number>();

/** 判重并入表：键 `${task_id}:${event_seq}`，命中=重复帧；
 * 新 seq 小于基线视为回绕/后端重启——重置基线并清该任务历史键（防新帧被旧键误判）；
 * 表超 500 条整体清空回绕（短窗口内可能漏去重，优于无界增长） */
export function isDuplicateEventSeq(taskId: string, seq: number): boolean {
  const key = `${taskId}:${seq}`;
  const baseline = seqBaselineByTask.get(taskId);
  if (baseline !== undefined && seq < baseline) {
    for (const seen of [...seenEventKeys]) {
      if (seen.startsWith(`${taskId}:`)) seenEventKeys.delete(seen);
    }
  }
  seqBaselineByTask.set(taskId, seq);
  if (seenEventKeys.has(key)) return true;
  seenEventKeys.add(key);
  if (seenEventKeys.size > EVENT_SEQ_SEEN_LIMIT) seenEventKeys.clear();
  return false;
}

/** 重置去重表（测试用） */
export function resetEventSeqDedupe(): void {
  seenEventKeys.clear();
  seqBaselineByTask.clear();
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

    // event_seq 帧级去重：重复帧整体跳过（含未读角标/日志刷新）；无字段帧兼容不去重
    if (ev.task_id && typeof ev.event_seq === 'number'
      && isDuplicateEventSeq(ev.task_id, ev.event_seq)) return;

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
    if (manualTaskIds.has(taskId)) {
      // 事件驱动释放：终态帧到达 = 手动路径处理完成，主动移除（不再只等 TTL）
      if (ev.status === 'succeeded' || ev.status === 'failed') manualTaskIds.delete(taskId);
      return; // 手动路径自行处理
    }

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
