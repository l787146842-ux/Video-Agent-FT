/**
 * SSE 流式请求封装（api 层）
 * 将 Agent 聊天的 HTTP POST + ReadableStream 读取集中于此，
 * hooks/use-sse.ts 只负责事件分发与状态管理。
 */
import type { AgentChatRequest } from '@/types';
import type { GuidanceItem } from '@/types/api.generated';
import { apiFetch, apiPost } from './client';

export interface SseStreamHandle {
  reader: ReadableStreamDefaultReader<Uint8Array>;
  abort: () => void;
}

/**
 * 发起 Agent 流式聊天请求，返回 ReadableStream reader。
 * 调用方负责逐块读取并解析 SSE 事件。
 */
export async function postAgentChatStream(
  request: AgentChatRequest,
  signal: AbortSignal,
): Promise<Response> {
  const res = await fetch('/api/agent/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  });
  return res;
}

// ===== 任务式传输（D 批）：后台任务 + 事件订阅，刷新/切项目不中断 =====

export interface AgentTaskInfo {
  task_id: string;
  project_id: string;
  status: string;
  created_at: number;
  status_text?: string;
}

export function startAgentTask(request: AgentChatRequest) {
  return apiPost<{ task_id: string; project_id: string }>('/api/agent/tasks', request);
}

export async function fetchAgentTaskEvents(taskId: string, signal: AbortSignal): Promise<Response> {
  return fetch(`/api/agent/tasks/${encodeURIComponent(taskId)}/events`, { signal });
}

export async function listAgentTasks(projectId: string): Promise<AgentTaskInfo[]> {
  const data = await apiFetch<{ tasks: AgentTaskInfo[] }>(
    `/api/agent/tasks?project_id=${encodeURIComponent(projectId)}`,
  );
  return data.tasks || [];
}

export function stopAgentTask(taskId: string) {
  return apiPost<{ ok: boolean; cancelled: number }>(
    `/api/agent/tasks/${encodeURIComponent(taskId)}/stop`,
    {},
  );
}

/** B0/F2：把排队消息登记到运行中任务，供后端轮间注入（任务已结束则后端拒绝）。 */
export function postAgentTaskGuidance(taskId: string, id: string, text: string) {
  const body: GuidanceItem = { id, text };
  return apiPost<{ ok: boolean }>(
    `/api/agent/tasks/${encodeURIComponent(taskId)}/guidance`,
    body,
  );
}
