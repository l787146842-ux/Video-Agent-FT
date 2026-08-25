/**
 * Agent 后台任务流式订阅——Solid 响应式封装层（任务 #18 瘦身）。
 *
 * 连接状态机纯逻辑在 lib/sse-connection（归属/重连调度/终态清理顺序），
 * 事件路由在 lib/sse-events（replay 快照 → 增量）；本文件只做 signal 接线、
 * 传输层与 store 副作用的依赖注入装配，并导出对外 API（语义零变化）。
 */
import { createSignal } from 'solid-js';
import type { AgentChatRequest } from '@/types';
import { chatActions } from '@/stores/chat';
import { convActions } from '@/stores/conversations';
import { state, studioActions } from '@/stores/studio';
import { showToast } from '@/stores/toast';
import { refreshHistoryStatus } from '@/stores/history';
import { applyFallbackModel } from '@/stores/agent-prefs';
import {
  startAgentTask, fetchAgentTaskEvents, stopAgentTask, listAgentTasks, postAgentTaskGuidance,
} from '@/api/sse';
import { requestInsertMedia } from '@/lib/chat/chat-input-bridge';
import { createSseConnection } from '@/lib/sse-connection';
import type { SseEventFx } from '@/lib/sse-events';

const [streaming, setStreaming] = createSignal(false);
const [error, setError] = createSignal<string | null>(null);

/** 响应式/跨 store 副作用注入（纯逻辑层不 import 任何 store 运行时） */
const fx: SseEventFx = {
  chat: chatActions,
  setStreaming: (v) => setStreaming(v),
  setErrorText: (m) => setError(m),
  setAgentBusy: (v) => studioActions.setAgentBusy(v),
  syncSnapshot: (s) => { studioActions.syncFromServer(s); convActions.syncFromServer(s); },
  markBoardApplied: () => studioActions.markBoardApplied(),
  applyFallbackModel: (provider, model) => applyFallbackModel(provider, model),
  toast: (msg, level) => showToast(msg, level),
  insertMedia: (media) => requestInsertMedia(media),
  refreshHistory: () => { void refreshHistoryStatus(); },
  now: () => Date.now(),
};

const conn = createSseConnection({
  transport: {
    startTask: startAgentTask,
    fetchEvents: fetchAgentTaskEvents,
    stopTask: stopAgentTask,
    listTasks: listAgentTasks,
    postGuidance: postAgentTaskGuidance,
    delay: (ms) => new Promise((r) => setTimeout(r, ms)),
  },
  fx,
  isStreaming: streaming,
  currentProjectId: () => state.projectId || '',
});

/** 发起 Agent 聊天：后台建任务 + 订阅事件流 */
export function streamAgentChat(request: AgentChatRequest): Promise<void> {
  return conn.streamAgentChat(request);
}

/** 接管外部已启动的 agent 任务（截断重答 /chat/truncate-resend 专用） */
export function attachStartedTask(
  started: { task_id: string; project_id: string; model?: string },
): Promise<void> {
  return conn.attachStartedTask(started);
}

/** 断开订阅但保留后台任务（切项目/离开页面时调用） */
export function disconnectAgentStream(): void {
  conn.disconnect();
}

/** 排队消息登记到运行中任务（轮间注入，不打断当前轮） */
export function sendGuidanceToTask(id: string, text: string): void {
  conn.sendGuidance(id, text);
}

/** 真正停止后台任务（停止按钮；与 /stop 1500ms 竞速不阻塞 UI） */
export function stopAgentStream(): Promise<void> {
  return conn.stop();
}

/** 刷新/切回项目后恢复进行中的后台任务（双触发互斥只进一次） */
export function resumeAgentTasks(projectId: string): Promise<void> {
  return conn.resume(projectId);
}

/** parseSSE 帧解析失败计数（不静默：调试可见，异常帧不中断流） */
export function getSseParseErrorCount(): number {
  return conn.getParseErrorCount();
}

/** 组件内使用的响应式封装 */
export function useAgentStream() {
  return { send: streamAgentChat, stop: stopAgentStream, streaming, error };
}
