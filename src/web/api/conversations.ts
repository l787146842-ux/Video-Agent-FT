/**
 * 多对话管理 API（同一项目多个对话窗口）
 * 端点：/api/conversations（GET/POST/DELETE/{id}/activate）
 * 所有响应统一为 ConversationsPayload，前端据此整体刷新标签栏。
 */
import { apiFetch, apiPost, apiDelete } from './client';
import type { Conversation } from '@/types';
import type { BranchRequest, CreateConversationRequest, SnapshotRequest } from '@/types/api.generated';

export interface ConversationsPayload {
  conversations: Conversation[];
  active_conversation_id: string;
}

/** 列出当前项目全部对话（含消息）+ 活跃对话 ID */
export function getConversations(): Promise<ConversationsPayload> {
  return apiFetch<ConversationsPayload>('/api/conversations');
}

/** 新建对话并设为活跃 */
export function createConversation(title = ''): Promise<ConversationsPayload> {
  const body: CreateConversationRequest = { title };
  return apiPost<ConversationsPayload>('/api/conversations', body);
}

/** 切换活跃对话 */
export function activateConversation(id: string): Promise<ConversationsPayload> {
  return apiPost<ConversationsPayload>(`/api/conversations/${encodeURIComponent(id)}/activate`, {});
}

/** 删除对话（仅剩一个时后端拒绝，抛 ApiError） */
export function deleteConversation(id: string): Promise<ConversationsPayload> {
  return apiDelete<ConversationsPayload>(`/api/conversations/${encodeURIComponent(id)}`);
}

/** B11：把当前活跃对话打为不可变快照。
 * upToIndex（可选，分叉点）：仅截取至该索引（含）；越界后端 400
 * （SNAPSHOT_INDEX_OUT_OF_RANGE）。不传 = 全量快照（旧行为）。 */
export function createSnapshot(upToIndex?: number): Promise<{ snap_id: string; title: string }> {
  const body: SnapshotRequest = upToIndex == null ? {} : { up_to_index: upToIndex };
  return apiPost<{ snap_id: string; title: string }>('/api/conversations/snapshot', body);
}

/** B11：从快照派生分支对话（新对话装载快照消息并设为活跃） */
export function branchSnapshot(snapId: string, title = ''): Promise<ConversationsPayload> {
  const body: BranchRequest = { title };
  return apiPost<ConversationsPayload>(
    `/api/conversations/snapshots/${encodeURIComponent(snapId)}/branch`, body,
  );
}
