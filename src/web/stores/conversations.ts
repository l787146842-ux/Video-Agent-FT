/**
 * 多对话状态管理（同一项目多个对话窗口）
 * 标签栏数据来自后端 /api/conversations；切换对话时装载目标对话消息到 chat store。
 * Agent 流式回复写入后端活跃对话，SSE done 快照带回最新 conversations 由 syncFromServer 刷新。
 */
import { createStore, produce } from 'solid-js/store';
import type { Conversation, ServerStateSnapshot } from '@/types';
import {
  createConversation as apiCreate,
  deleteConversation as apiDelete,
  activateConversation as apiActivate,
  type ConversationsPayload,
} from '@/api/conversations';
import { chatActions } from './chat';
import { showToast } from './toast';

export interface ConversationsState {
  list: Conversation[];
  activeId: string;
}

const [convState, setConvState] = createStore<ConversationsState>({
  list: [],
  activeId: '',
});

/** 后端 payload → store，并按需把活跃对话消息装载进 chat store */
function applyPayload(
  payload: ConversationsPayload,
  loadActiveMessages: boolean,
) {
  setConvState(produce((s) => {
    s.list = payload.conversations || [];
    s.activeId = payload.active_conversation_id || '';
  }));
  if (loadActiveMessages) {
    const active = convState.list.find((c) => c.id === convState.activeId);
    chatActions.loadMessages(active?.messages || []);
  }
}

export const convActions = {
  /** 初始加载 / 项目切换：从状态快照装载（快照无 conversations 时清空标签栏） */
  loadFromSnapshot(snapshot: ServerStateSnapshot | null) {
    const convs = snapshot?.conversations;
    if (!Array.isArray(convs) || convs.length === 0) {
      setConvState({ list: [], activeId: '' });
      return;
    }
    setConvState(produce((s) => {
      s.list = convs;
      s.activeId = snapshot?.activeConversationId || convs[0].id;
    }));
  },

  /** SSE done 快照同步：刷新各对话消息与活跃态（不重载 chat，避免冲掉本地流式状态） */
  syncFromServer(snapshot: ServerStateSnapshot) {
    const convs = snapshot.conversations;
    if (!Array.isArray(convs) || convs.length === 0) return;
    setConvState(produce((s) => {
      s.list = convs;
      s.activeId = snapshot.activeConversationId || s.activeId;
    }));
  },

  /** B11：分支操作后整体应用后端 payload（含消息装载） */
  applyPayload(payload: ConversationsPayload) {
    applyPayload(payload, true);
  },

  /** 新建对话（+ 号）：成功后切换到空白新对话 */
  async create(): Promise<boolean> {
    try {
      const payload = await apiCreate();
      applyPayload(payload, true);
      return true;
    } catch (e) {
      showToast(`新建对话失败：${(e as Error).message}`, 'error');
      return false;
    }
  },

  /** 切换活跃对话：装载目标对话的历史消息 */
  async activate(id: string) {
    if (id === convState.activeId) return;
    try {
      const payload = await apiActivate(id);
      applyPayload(payload, true);
    } catch (e) {
      showToast(`切换对话失败：${(e as Error).message}`, 'error');
    }
  },

  /** 关闭对话（仅剩一个时不允许，前端不渲染关闭钮 + 后端兜底） */
  async close(id: string) {
    if (convState.list.length <= 1) return;
    try {
      const payload = await apiDelete(id);
      applyPayload(payload, true);
    } catch (e) {
      showToast(`关闭对话失败：${(e as Error).message}`, 'error');
    }
  },
};

export { convState, setConvState };
