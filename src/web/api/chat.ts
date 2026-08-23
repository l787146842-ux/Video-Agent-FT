/**
 * /api/chat — 截断重答（edit-and-resend，任务 #16 后端契约的前端封装）。
 *
 * 语义：后端丢弃最后一条用户消息之后的全部消息（真正删除）→
 * text 非空且与原文不同时替换该消息正文 → 起 agent 任务；
 * 响应体与 /api/agent/tasks 一致（{task_id, project_id}），
 * 前端经 use-sse.attachStartedTask 接管既有事件订阅路径。
 *
 * 错误：400 NO_USER_MESSAGE / EMPTY_MESSAGE；409 AGENT_BUSY（ErrorPayload 契约）。
 */
import { apiPost } from './client';
import type { TruncateResendRequest } from '@/types/api.generated';

export interface TruncateResendResponse {
  task_id: string;
  project_id: string;
  /** 后端实际起任务用的模型（前端据此 startStream(model) 补流式模型徽标） */
  model?: string;
}

/** 截断重答：text 缺省 = 重新生成（按原文重答）；非空 = 编辑后重答。
 *  provider/model/thinking_level 取自 UI 当前选中态（与主输入框同口径） */
export function truncateResend(
  text?: string | null,
  target?: { provider?: string; model?: string; thinking_level?: string },
): Promise<TruncateResendResponse> {
  const body: TruncateResendRequest = {
    ...(text != null ? { text } : {}),
    ...(target?.provider ? { provider: target.provider } : {}),
    ...(target?.model ? { model: target.model } : {}),
    ...(target?.thinking_level ? { thinking_level: target.thinking_level } : {}),
  };
  return apiPost<TruncateResendResponse>('/api/chat/truncate-resend', body);
}
