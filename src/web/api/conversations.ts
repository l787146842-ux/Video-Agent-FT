/**
 * 多对话管理 API（同一项目多个对话窗口）
 * 端点：/api/conversations（GET/POST/DELETE/{id}/activate/{id}/messages）
 * 对话列表/增删切响应统一为 ConversationsPayload（仅元信息，E-2 消息单一来源），
 * 前端据此刷新标签栏；目标对话消息经 getConversationMessages 单独装载。
 */
import { apiFetch, apiPost, apiDelete } from './client';
import type { ChatMessage } from '@/types';
import type {
  BranchRequest, ConversationsMetaResponse, CreateConversationRequest, SnapshotRequest,
} from '@/types/api.generated';

/** 对话列表/增删切响应（后端 ConversationsMetaResponse 生成物为唯一来源；
 * 别名仅保消费方旧名，无二次收窄） */
export type ConversationsPayload = ConversationsMetaResponse;

/** 按会话拉消息的响应（消息单一来源装载接口） */
export interface ConversationMessagesResponse {
  conversation_id: string;
  messages: ChatMessage[];
}

/** 列出当前项目全部对话（元信息，不含消息）+ 活跃对话 ID */
export function getConversations(): Promise<ConversationsPayload> {
  return apiFetch<ConversationsPayload>('/api/conversations');
}

/** 按会话 ID 拉消息（切会话/新建/关闭/分支后装载目标对话历史的唯一通道） */
export function getConversationMessages(id: string): Promise<ConversationMessagesResponse> {
  return apiFetch<ConversationMessagesResponse>(
    `/api/conversations/${encodeURIComponent(id)}/messages`,
  );
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
 * （SNAPSHOT_INDEX_OUT_OF_RANGE）。不传 = 全量快照（旧行为）。
 * 响应 pruned：本次创建触发数量上限淘汰时被清理的快照 id 清单
 * （非空时前端 toast 提示，淘汰对用户可见）。 */
export interface CreateSnapshotResponse {
  snap_id: string;
  title: string;
  /** 本次创建时被自动淘汰的快照 id 清单（空 = 未触发淘汰） */
  pruned: string[];
}

export function createSnapshot(upToIndex?: number): Promise<CreateSnapshotResponse> {
  const body: SnapshotRequest = upToIndex == null ? {} : { up_to_index: upToIndex };
  return apiPost<CreateSnapshotResponse>('/api/conversations/snapshot', body);
}

/** B11：从快照派生分支对话（新对话装载快照消息并设为活跃） */
export function branchSnapshot(snapId: string, title = ''): Promise<ConversationsPayload> {
  const body: BranchRequest = { title };
  return apiPost<ConversationsPayload>(
    `/api/conversations/snapshots/${encodeURIComponent(snapId)}/branch`, body,
  );
}
