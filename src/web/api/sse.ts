/**
 * SSE 流式请求封装（api 层）
 * 任务式传输（POST 建任务 + 事件订阅）的 HTTP 封装集中于此，
 * hooks/use-sse.ts 只负责事件分发与状态管理。
 * ：旧 postAgentChatStream（POST /api/agent/chat/stream 直连流）为死代码——
 * 真实链路已全量走任务式传输（startAgentTask + fetchAgentTaskEvents），已删除；
 * 后端同名路由已同步清退（routes/agent.py 只保留任务式端点）。
 */
import type { AgentChatRequest } from '@/types';
import type { GuidanceItem } from '@/types/api.generated';
import { apiFetch, apiPost, buildAuthHeaders } from './client';

// ===== 任务式传输：后台任务 + 事件订阅，刷新/切项目不中断 =====

export interface AgentTaskInfo {
  task_id: string;
  project_id: string;
  /** 任务绑定的对话（批 6-2 多会话并行：事件流路由/忙态角标用）；
   *  旧任务记录可能缺省（回落活跃对话口径） */
  conversation_id?: string;
  status: string;
  created_at: number;
  status_text?: string;
}

export function startAgentTask(request: AgentChatRequest) {
  return apiPost<{ task_id: string; project_id: string }>('/api/agent/tasks', request);
}

export async function fetchAgentTaskEvents(taskId: string, signal: AbortSignal): Promise<Response> {
  // 鉴权头经 client 唯一出口注入（任务7/P0）：生产模式 api_key_auth 对
  // /api/ 强制 X-API-Key，裸 fetch 必 401；SSE 流式响应由调用方读流，
  // 故不走 apiFetch（其只解析 JSON）。
  return fetch(`/api/agent/tasks/${encodeURIComponent(taskId)}/events`, {
    headers: buildAuthHeaders(),
    signal,
  });
}

export async function listAgentTasks(projectId: string): Promise<AgentTaskInfo[]> {
  const data = await apiFetch<{ tasks: AgentTaskInfo[] }>(
    `/api/agent/tasks?project_id=${encodeURIComponent(projectId)}`,
  );
  return data.tasks || [];
}

export function stopAgentTask(taskId: string) {
  // 响应新增 inflight（在途外部生成任务登记，停止气泡文案消费）
  return apiPost<{ ok: boolean; cancelled: number; inflight?: Array<{ task_id?: string; media_type?: string; model?: string; summary?: string }> }>(
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
