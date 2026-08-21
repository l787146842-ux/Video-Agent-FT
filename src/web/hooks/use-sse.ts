/* eslint-disable max-lines */ // 后台任务订阅协调中枢，事件类型多、行数超限属合理
import { createSignal } from 'solid-js';
import type { SseEvent, SseDonePayload, AgentChatRequest } from '@/types';
import { chatActions } from '@/stores/chat';
import { convActions } from '@/stores/conversations';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { refreshHistoryStatus } from '@/stores/history';
import { resolveErrorMessage } from '@/lib/i18n';
import { t } from '@/lib/locale';
import {
  startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks,
  postAgentTaskGuidance,
  type AgentTaskInfo,
} from '@/api/sse';
import { requestInsertMedia } from '@/lib/chat-input-bridge';
import { applyFallbackModel } from '@/stores/agent-prefs';
import { uid } from '@/lib/utils';

/** Agent 后台任务流式订阅（D 批）：POST 取 task_id → 订阅事件（先 replay 再增量）。
 * 刷新/切项目只断开订阅，后台任务继续；切回时 resumeAgentTasks 重连；停止才取消。 */
const [streaming, setStreaming] = createSignal(false);
const [error, setError] = createSignal<string | null>(null);

let abortController: AbortController | null = null;
let currentTask: { taskId: string; projectId: string; recovering: boolean } | null = null;
/** 每个项目仍在后台运行的任务（切走后记住，切回时恢复订阅） */
const projectTasks = new Map<string, string>();

/** SSE 自动重连（批1 审核整改）：后台任务在断连期间继续运行，
 * 网络抖动不得落错误气泡/清忙态；指数退避重订阅（服务端先 replay 快照再增量，
 * restoreStreamingState 整体替换累积文本，天然幂等）。重试耗尽才落错误。 */
const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_BASE_DELAY_MS = 500;
/** resumeAgentTasks 双触发互斥（LayoutShell onMount 与 project effect 竞态窗口） */
let resumeInFlight = false;
/** parseSSE 帧解析失败计数（不静默：调试可见，异常帧不中断流） */
let sseParseErrors = 0;
export function getSseParseErrorCount(): number { return sseParseErrors; }

/** 事件订阅 HTTP 失败：携带 status 供重连策略判定（4xx 任务面错误不重连） */
export class SseHttpError extends Error {
  constructor(public readonly status: number) {
    super(`事件订阅失败 (${status})`);
    this.name = 'SseHttpError';
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function parseSSE(res: Response, onEvent: (ev: SseEvent) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    (async () => {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const raw = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 2);
            if (!raw.startsWith('data:')) continue;
            const jsonStr = raw.slice(5).trim();
            if (jsonStr === '[DONE]') continue;
            try {
              onEvent(JSON.parse(jsonStr) as SseEvent);
            } catch {
              // 异常帧不中断流：计数+告警（静默吞错曾掩盖契约漂移）
              sseParseErrors += 1;
              console.warn(`[use-sse] SSE 帧解析失败（累计 ${sseParseErrors} 次）`);
            }
          }
        }
        resolve();
      } catch (err) {
        reject(err);
      }
    })();
  });
}

/** 关闭当前订阅（不取消后台任务） */
function closeSubscription() {
  abortController?.abort();
  abortController = null;
}

async function subscribeOnce(taskId: string): Promise<void> {
  abortController = new AbortController();
  const res = await fetchAgentTaskEvents(taskId, abortController.signal);
  if (!res.ok || !res.body) throw new SseHttpError(res.status);
  await parseSSE(res, (ev) => handleEvent(ev));
}

/** 订阅失败判定：true = 网络/传输层瞬断，值得重连（后台任务仍在跑）；
 * false = 用户取消或任务面错误（4xx：任务不存在/已结束被清理），重连无意义。
 * 导出供单测钉死（批1 验收）。 */
export function isRetriableSubscribeError(err: unknown): boolean {
  if ((err as Error).name === 'AbortError') return false;
  if (err instanceof SseHttpError) {
    // 408/429 属瞬态可重连；其余 4xx = 任务面错误
    return err.status === 408 || err.status === 429 || err.status >= 500;
  }
  return true; // fetch 网络错误 / 读流中断
}

async function connectToTask(taskId: string, projectId: string, recovering: boolean): Promise<void> {
  setStreaming(true);
  studioActions.setAgentBusy(true);
  currentTask = { taskId, projectId, recovering };

  let attempt = 0;
  while (true) {
    try {
      await subscribeOnce(taskId);
      break; // 流正常结束（done/error 事件已在 handleEvent 内收尾）
    } catch (err) {
      // 任务归属已变（停止/切换/断开）：不再处理本任务的失败
      if (currentTask?.taskId !== taskId) return;
      if (!isRetriableSubscribeError(err) || attempt >= MAX_RECONNECT_ATTEMPTS) {
        const msg = (err as Error).message || '未知错误';
        setError(msg);
        chatActions.streamError(msg);
        break;
      }
      // 指数退避重订阅：忙态保持 true（后台任务未停），replay 快照幂等恢复
      attempt += 1;
      const waitMs = RECONNECT_BASE_DELAY_MS * 2 ** (attempt - 1);
      chatActions.setStatus(t('rp.streaming.reconnecting', { attempt, max: MAX_RECONNECT_ATTEMPTS }));
      await delay(waitMs);
      if (currentTask?.taskId !== taskId) return; // 等待期间归属变化
    }
  }
  // 仅当仍订阅本任务时清理（disconnectAgentStream/handleDone 已把 currentTask 置空）
  if (currentTask?.taskId === taskId) {
    setStreaming(false);
    studioActions.setAgentBusy(false);
    currentTask = null;
    abortController = null;
    if (projectTasks.get(projectId) === taskId) projectTasks.delete(projectId);
  }
}

/** 发起 Agent 聊天：后台建任务 + 订阅事件流 */
export async function streamAgentChat(request: AgentChatRequest): Promise<void> {
  if (streaming()) return;
  const projectId = state.projectId || '';
  setError(null);
  studioActions.setAgentBusy(true);
  chatActions.startStream(request.model || '');
  try {
    const started = await startAgentTask(request);
    projectTasks.set(started.project_id || projectId, started.task_id);
    await connectToTask(started.task_id, started.project_id || projectId, false);
  } catch (err) {
    const msg = (err as Error).message || '未知错误';
    setError(msg);
    chatActions.streamError(msg);
    studioActions.setAgentBusy(false);
  }
}

/** 断开订阅但保留后台任务（切项目/离开页面时调用） */
export function disconnectAgentStream(): void {
  if (currentTask) {
    projectTasks.set(currentTask.projectId, currentTask.taskId);
    currentTask = null;
  }
  closeSubscription();
  setStreaming(false);
  studioActions.setAgentBusy(false);
}

/** ：排队消息登记到运行中任务（轮间注入）；任务不存在/已结束静默回落
 * 前端「任务结束后自动出队重发」路径，不丢失用户消息。 */
export function sendGuidanceToTask(id: string, text: string): void {
  const task = currentTask;
  if (!task || !text.trim()) return;
  void postAgentTaskGuidance(task.taskId, id, text).catch(() => { /* 回落自动出队 */ });
}

/** 真正停止后台任务（停止按钮） */
export function stopAgentStream(): void {
  const task = currentTask;
  if (task) {
    void stopAgentTask(task.taskId).catch(() => { /* 任务可能已结束 */ });
    projectTasks.delete(task.projectId);
  }
  closeSubscription();
  chatActions.cancelStream();
  setStreaming(false);
  studioActions.setAgentBusy(false);
  currentTask = null;
}

/** 刷新 / 切回项目后恢复进行中的后台任务（互斥：onMount 与 project effect 双触发只进一次） */
export async function resumeAgentTasks(projectId: string): Promise<void> {
  if (!projectId || streaming() || resumeInFlight) return;
  resumeInFlight = true;
  try {
    let tasks: AgentTaskInfo[] = [];
    try {
      tasks = await listAgentTasks(projectId);
    } catch { /* 后端未就绪时静默 */ }
    if (!tasks.length) return;
    // await 之后再判一次：窗口内另一触发可能已建立订阅
    if (streaming()) return;
    const task = tasks[0]; // 最新任务
    projectTasks.set(projectId, task.task_id);
    chatActions.restoreStreamingState({
      reasoning: '',
      text: '',
      statusText: t('rp.streaming.restoring'),
      tools: [],
    });
    await connectToTask(task.task_id, projectId, true);
  } finally {
    resumeInFlight = false;
  }
}

function handleEvent(ev: SseEvent) {
  switch (ev.type) {
    case 'replay': {
      const p = ev.payload;
      if (!p) break;
      // 断连期间发生过降级：重连即把选择器补跳到实际生效的组合
      if (p.fallback?.model) applyFallbackModel(p.fallback.provider, p.fallback.model);
      // 任务已结束（断连期间完成）：直接采用服务端快照，避免消息重复
      if (p.status === 'done' && p.done_payload) {
        if (currentTask?.recovering) {
          if (p.snapshot) {
            studioActions.syncFromServer(p.snapshot);
            convActions.syncFromServer(p.snapshot);
          }
          if (p.snapshot?.chatMessages) chatActions.loadMessages(p.snapshot.chatMessages);
          chatActions.clearStreaming();
          setStreaming(false);
          studioActions.setAgentBusy(false);
          currentTask = null;
          if (p.project_id) projectTasks.delete(p.project_id);
          closeSubscription();
          showToast(t('rp.task.done'), 'success');
        } else {
          handleDone(p.done_payload);
        }
        break;
      }
      if (p.status === 'error') {
        chatActions.streamError(p.error || '任务已中断');
        setStreaming(false);
        studioActions.setAgentBusy(false);
        if (p.project_id) projectTasks.delete(p.project_id);
        currentTask = null;
        closeSubscription();
        break;
      }
      // 运行中：恢复累积状态后继续收实时增量
      // Rule2 v6：断连期间文档卡补渲染（task_manager 累积账本，
      // 瞬态 SSE 不得作为唯一可见性）
      (p.docs || []).forEach((n) => chatActions.docWritten(n));
  chatActions.restoreStreamingState({
    reasoning: p.reasoning || '',
    text: p.text || '',
    statusText: p.status_text || t('rp.streaming.processing'),
    tools: (p.tools || []).map((t) => ({
      id: t.id || '',
      name: t.name || '',
      summary: t.summary || '',
      status: (
        t.status === 'running' || t.status === 'done' || t.status === 'failed'
          ? t.status
          : 'running'
      ),
      elapsed_ms: t.elapsed_ms ?? undefined,
      result_summary: t.result_summary || '',
      // ：运行中走秒起点（replay 无原始起点时以恢复时刻为准）
      started_at_ms: t.started_at_ms ?? Date.now(),
    })),
    model: p.model || '',
  });
      if (p.snapshot) {
        studioActions.syncFromServer(p.snapshot);
        convActions.syncFromServer(p.snapshot);
      }
      break;
    }
    case 'status': {
      // ：固定文案按 key 走 locale 翻译（key 优先、字典缺失回退 text）
      const keyed = ev.key ? t(ev.key, ev.params) : '';
      chatActions.setStatus(keyed && keyed !== ev.key ? keyed : (ev.text || ''));
      break;
    }
    case 'delta':
      chatActions.appendDelta(ev.text || '');
      break;
    case 'reasoning_delta':
      chatActions.appendReasoning(ev.text || '');
      break;
    case 'tool_started':
      chatActions.toolStarted(ev.id, ev.name, ev.summary);
      break;
    case 'tool_finished':
      chatActions.toolFinished(ev.id, ev.ok, ev.elapsed_ms || 0, ev.result_summary);
      break;
    case 'doc_written':
      // ：携带后端打戳的 turn_id，即显卡与 done 主消息严格同组
      if (ev.name) chatActions.docWritten(ev.name, ev.turn_id);
      break;
    case 'model_fallback':
      // 降级即时联动：切换时刻就跳选择器，不等整轮成功
      applyFallbackModel(ev.provider, ev.model);
      break;
    case 'guidance_injected':
      // 引导消息轮间注入成功：渲染用户气泡并从排队区移除对应条目
      if (ev.text) chatActions.addMessage({ sender: 'user', text: ev.text });
      if (ev.id) chatActions.removeQueuedMessage(ev.id);
      break;
    case 'actions_applied': {
      const snapshot = ev.payload?.state;
      if (snapshot) {
        studioActions.syncFromServer(snapshot);
        convActions.syncFromServer(snapshot);
        studioActions.markBoardApplied();
      }
      break;
    }
    case 'done':
      handleDone(ev.payload);
      break;
    case 'task_status':
      // 任务状态变更（cancelled 等，批2 契约对齐）：后端下发后即关流，
      // 流结束走 connectToTask 正常收尾清理；此处显式消费不落 default
      break;
    case 'error': {
      const msg = resolveErrorMessage(ev.error_code, ev.detail || ev.text || '服务端错误');
      setError(msg);
      // ：上游原始报文随错误消息下发，前端折叠展示
      chatActions.streamError(msg, ev.raw || '');
      closeSubscription();
      break;
    }
    default:
      break;
  }
}

function handleDone(payload: SseDonePayload) {
  chatActions.finishStream(payload);
  if (payload.state) {
    studioActions.syncFromServer(payload.state);
    convActions.syncFromServer(payload.state);
  }
  void refreshHistoryStatus();
  const inserts = payload.chat_inserts || [];
  if (inserts.length) {
    const seen = new Set<string>();
    for (const it of inserts) {
      if (!it.url || seen.has(it.url)) continue;
      seen.add(it.url);
      requestInsertMedia({
        id: uid('im'), kind: it.kind, url: it.url,
        name: it.name || it.url, thumb: it.thumb || undefined,
      });
    }
    showToast(t('rp.msg.mediaInserted', { count: seen.size }), 'success');
  }
  if ((payload.applied_actions || 0) > 0) {
    studioActions.markBoardApplied();
  }
  // ：toast 收敛——操作数已由阶段卡徽标/meta 展示、警告已常驻消息内，
  // 不再重复弹 toast（信息已在对话内可见的只展示一处）
  // 任务已结束，关闭订阅（后台任务本身已完成，无需保留连接）
  if (currentTask) projectTasks.delete(currentTask.projectId);
  closeSubscription();
}

/** 组件内使用的响应式封装 */
export function useAgentStream() {
  return { send: streamAgentChat, stop: stopAgentStream, streaming, error };
}
