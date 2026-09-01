/**
 * Agent 后台任务流式订阅——Solid 响应式封装层（批 6-2：多任务并行注册表）。
 *
 * 连接状态机纯逻辑在 lib/sse-connection（归属/重连调度/终态清理顺序），
 * 事件路由在 lib/sse-events（replay 快照 → 增量），任务级分流面在
 * lib/sse-task-fx（live/shadow）；本文件只做注册表编排：每任务一条独立连接，
 * 同项目多对话并行互不串流（宪法 Rule 3 并发契约 Q25）；切换活跃对话时
 * 对目标任务重订阅（replay 快照幂等恢复累积状态）。
 */
import { createSignal } from 'solid-js';
import type { AgentChatRequest } from '@/types';
import { chatActions } from '@/stores/chat';
import { agentActions } from '@/stores/agent-state';
import { convState } from '@/stores/conversations';
import { state } from '@/stores/studio';
import {
  startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance,
} from '@/api/sse';
import { createSseConnection, type SseTransport } from '@/lib/sse-connection';
import { makeRoutedTaskFx } from '@/lib/sse-task-fx';
import { ApiError } from '@/api/client';
import { makeErrorPayload } from '@/lib/error-payload';
import { t } from '@/lib/locale';

const [streaming, setStreaming] = createSignal(false);
const [error, setError] = createSignal<string | null>(null);

const transport: SseTransport = {
  startTask: startAgentTask,
  fetchEvents: fetchAgentTaskEvents,
  stopTask: stopAgentTask,
  listTasks: listAgentTasks,
  postGuidance: postAgentTaskGuidance,
  delay: (ms) => new Promise((r) => setTimeout(r, ms)),
};

function currentProjectId(): string {
  return state.projectId || '';
}

interface TaskHandle {
  taskId: string;
  convId: string;
  projectId: string;
  conn: ReturnType<typeof createSseConnection>;
}

/** 连接注册表：每个后台任务一条独立连接 */
const conns = new Map<string, TaskHandle>();

/** 按任务创建定向连接：分流面见 lib/sse-task-fx（事件时刻按活跃对话判定） */
function spawnConnection(taskId: string, projectId: string, convId: string): TaskHandle {
  const fx = makeRoutedTaskFx(convId, taskId, { setStreaming, setError });
  const conn = createSseConnection({ transport, fx, isStreaming: streaming, currentProjectId });
  const handle: TaskHandle = { taskId, convId, projectId, conn };
  conns.set(taskId, handle);
  return handle;
}

/** 活跃对话的任务连接（停止/引导寻址）；回落：无匹配时取任一连接（单任务旧语义） */
function activeTaskHandle(): TaskHandle | null {
  const active = convState.activeId || '';
  for (const h of conns.values()) {
    if (h.convId === active) return h;
  }
  for (const h of conns.values()) {
    if (h.convId === '') return h;
  }
  const first = conns.values().next();
  return first.done ? null : first.value;
}

/** 发起 Agent 聊天：后台建任务 + 订阅事件流（同对话已有任务运行时拒发） */
async function streamAgentChat(request: AgentChatRequest): Promise<void> {
  const convId = request.conversation_id || convState.activeId || '';
  if (agentActions.isConvBusy(convId)) return;
  setError(null);
  agentActions.setConvBusy(convId, '');
  chatActions.startStream(request.model || '');
  try {
    const started = await transport.startTask(request);
    agentActions.setConvBusy(convId, started.task_id);
    const handle = spawnConnection(started.task_id, started.project_id || currentProjectId(), convId);
    await handle.conn.attachStartedTask({
      task_id: started.task_id,
      project_id: started.project_id || currentProjectId(),
      model: request.model || '',
    });
  } catch (err) {
    agentActions.clearConvBusy(convId);
    setStreaming(false);
    // 建任务失败归类（与单连接时代同口径）：ApiError 携带后端结构化负载；
    // 非 ApiError（fetch 网络层）归 network
    const payload = err instanceof ApiError ? err.payload
      : makeErrorPayload((err as Error).message || '未知错误', 'network', 'err.network.connection');
    setError(payload.message);
    chatActions.streamError(payload);
  }
}

/** 接管外部已启动的 agent 任务（截断重答 /chat/truncate-resend 专用） */
async function attachStartedTask(
  started: { task_id: string; project_id: string; model?: string },
  conversationId?: string,
): Promise<void> {
  const convId = conversationId || convState.activeId || '';
  if (conns.has(started.task_id)) return;
  setError(null);
  agentActions.setConvBusy(convId, started.task_id);
  chatActions.startStream(started.model || '');
  const handle = spawnConnection(started.task_id, started.project_id || currentProjectId(), convId);
  await handle.conn.attachStartedTask(started);
}

/** 断开全部订阅但保留后台任务（切项目/离开页面时调用）；忙态清零
 *  与单连接时代语义一致（切走不再显示忙碌，切回由 resume 重建） */
function disconnect(): void {
  for (const h of conns.values()) h.conn.disconnect();
  conns.clear();
  agentActions.setAgentBusy(false);
  setStreaming(false);
}

/** 排队消息登记到运行中任务（轮间注入）：定向当前活跃对话的任务 */
function sendGuidance(id: string, text: string): void {
  const h = activeTaskHandle();
  if (!h || !text.trim()) return;
  void transport.postGuidance(h.taskId, id, text).catch(() => { /* 回落自动出队 */ });
}

/** 真正停止后台任务（停止按钮）：停当前活跃对话的任务 */
async function stop(): Promise<void> {
  const h = activeTaskHandle();
  if (!h) {
    chatActions.cancelStream({});
    setStreaming(false);
    return;
  }
  await h.conn.stop();
  conns.delete(h.taskId);
}

/** 刷新/切回项目后恢复进行中的后台任务（全部并行订阅） */
async function resume(projectId: string): Promise<void> {
  if (!projectId) return;
  let tasks: Awaited<ReturnType<typeof listAgentTasks>> = [];
  try {
    tasks = await listAgentTasks(projectId);
  } catch { /* 后端未就绪时静默 */ }
  const active = convState.activeId || '';
  let liveRestored = false;
  const jobs: Array<Promise<void>> = [];
  for (const task of tasks) {
    if (conns.has(task.task_id)) continue;
    const convId = task.conversation_id || '';
    agentActions.setConvBusy(convId, task.task_id);
    const handle = spawnConnection(task.task_id, projectId, convId);
    const live = convId === active || convId === '';
    if (live && !liveRestored) {
      chatActions.restoreStreamingState({
        reasoning: '', text: '', statusText: t('rp.streaming.restoring'), tools: [],
      });
      liveRestored = true;
    }
    jobs.push(handle.conn.recoverTask(task.task_id, projectId).then(() => {
      if (!agentActions.taskOfConv(convId)) conns.delete(task.task_id); // 终态已收尾
    }));
  }
  await Promise.all(jobs);
}

/** 切换活跃对话（批 6-2）：未读角标清除 → 清当前视图流式态 →
 *  目标对话有运行中任务时重订阅拿 replay 恢复累积状态 */
function focusConversation(conversationId: string): void {
  if (!conversationId) return;
  agentActions.clearUnread(conversationId);
  chatActions.clearStreaming();
  setStreaming(false);
  for (const h of conns.values()) {
    if (h.convId !== conversationId) continue;
    agentActions.setConvBusy(conversationId, h.taskId);
    chatActions.restoreStreamingState({
      reasoning: '', text: '', statusText: t('rp.streaming.restoring'), tools: [],
    });
    // 强制重订阅：即使已在订阅也重拿 replay，把累积状态重建进聊天区（后台转前台）
    void h.conn.recoverTask(h.taskId, h.projectId, true);
    break;
  }
}

/** parseSSE 帧解析失败计数（各连接汇总；不静默，异常帧不中断流） */
function getSseParseErrorCount(): number {
  let n = 0;
  for (const h of conns.values()) n += h.conn.getParseErrorCount();
  return n;
}

/** 组件内使用的响应式封装 */
export function useAgentStream() {
  return { send: streamAgentChat, stop, streaming, error };
}

export {
  streamAgentChat, attachStartedTask, disconnect as disconnectAgentStream,
  sendGuidance as sendGuidanceToTask, stop as stopAgentStream,
  resume as resumeAgentTasks, focusConversation, getSseParseErrorCount,
};
